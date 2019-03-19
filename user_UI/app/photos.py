import datetime
import hashlib

import cv2
import numpy
import uuid
import boto3
from flask import render_template, redirect, url_for, request, g, session
from wand.image import Image
import os
from io import BytesIO
import urllib.request

from app import webapp
from app.db import get_db

s3_bucketName = 'ece1779imagesstorage'

ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg', 'gif'])
TYPE_ORIGINAL = 1
TYPE_THUMBNAIL = 2
TYPE_FACE_DETECTED = 3

face_cascade = cv2.CascadeClassifier(os.path.join(cv2.haarcascades, 'haarcascade_frontalface_default.xml'))

@webapp.teardown_appcontext
def teardown_db(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@webapp.route('/', methods=['GET'])
@webapp.route('/album', methods=['GET'])
#Return html with thumbnails of all photos for the current user
def thumbnails():
    if 'authenticated' not in session:
        return redirect(url_for('login'))

    cnx = get_db()

    cursor = cnx.cursor()

    query = "SELECT p.id, t.filename " \
            "FROM photo p, storedphoto t " \
            "WHERE p.id = t.photo_id AND " \
            "      t.type_id = 2 AND " \
            "      p.user_id = %s "


    try:
        cursor.execute(query, (session['user_id'],))
        user_id = session['user_id']
        photo_id_list = []
        url_list = []
        filename_list = []

        for row in cursor:
            photo_id = row[0]
            filename = row[1]
            photo_id_list.append(photo_id)
            filename_list.append(filename)

            file_key_name_thumb = str(user_id) + '/' + filename
            s3 = boto3.client('s3',region_name='us-east-1')
            url = s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': s3_bucketName, 'Key': file_key_name_thumb})

            url_list.append(url)

    except Exception as e:
        return e.msg

    zipped_data = zip(photo_id_list, url_list, filename_list)
    return render_template("photos/album.html",zipped_data=zipped_data)

@webapp.route('/photo/<int:photo_id>',methods=['GET'])
#Return html with alls the versions of a given photo
def details(photo_id):
    if 'authenticated' not in session:
        return redirect(url_for('login'))

    try:
        url_list = []
        cnx = get_db()
        cursor = cnx.cursor()

        # create a new tuple for the photo and store the
        query = "SELECT t.filename " \
                "FROM storedphoto t, photo p " \
                "WHERE t.photo_id = p.id AND " \
                "      p.id = %s AND " \
                "      p.user_id = %s AND " \
                "      t.type_id = 1"
        cursor.execute(query, (photo_id,session['user_id']))

        row = cursor.fetchone()
        file_orig = row[0]

        # create a new tuple for the photo and store the
        query = "SELECT t.filename " \
                "FROM storedphoto t, photo p " \
                "WHERE t.photo_id = p.id AND " \
                "      p.id = %s AND " \
                "      p.user_id = %s AND " \
                "      t.type_id = 3"
        cursor.execute(query, (photo_id, session['user_id']))
        row = cursor.fetchone()
        file_df = row[0]

        user_id = session['user_id']
        file_key_name_orig = str(user_id) + '/' + file_orig
        s3 = boto3.client('s3', region_name='us-east-1')
        url_orig = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': s3_bucketName, 'Key': file_key_name_orig})

        file_key_name_df = str(user_id) + '/' + file_df
        s3 = boto3.client('s3', region_name='us-east-1')
        url_df = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': s3_bucketName, 'Key': file_key_name_df})

        url_list = [url_orig, url_df]

    except Exception as e:
            return e.msg

    return render_template("photos/details.html",url_list=url_list)


@webapp.route('/upload_form',methods=['GET'])
#Returns an html form for uploading a new photo
def upload_form():
    if 'authenticated' not in session:
        return redirect(url_for('login'))

    e = None

    if 'error' in session:
        e = session['error']
        session.pop('error')


    return render_template("photos/upload_form.html", error=e)

def filename_extension(filename):
    _, file_extension = os.path.splitext(filename)
    return file_extension[1:]

def is_allowed_file(filename):
    return '.' in filename and filename_extension(filename) in ALLOWED_EXTENSIONS


@webapp.route('/upload_save', methods=['POST'])
#Handles photo upload and the creation of a thumbnail and three transformations
def upload_save():
    if 'authenticated' not in session:
        return redirect(url_for('upload_form'))

    # check if the post request has the file part
    if 'uploadedfile' not in request.files:
        session['error'] = "Missing uploaded file"
        return redirect(url_for('upload_form'))

    new_file = request.files['uploadedfile']

    # if user does not select file, browser also
    # submit a empty part without filename
    if new_file.filename == '':
        session['error'] = 'Missing file name'
        return redirect(url_for('upload_form'))

    if is_allowed_file(new_file.filename) == False:
        session['error'] = 'File type not supported'
        return redirect(url_for('upload_form'))

    try:
        process_file(session['user_id'], new_file)
    except Exception as e:
        session['error'] = 'Unable to process file: ' + e
        return redirect(url_for('upload_form'))

    return redirect(url_for('thumbnails'))


def process_file(user_id, new_file):
    store_base = "I" + datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S') + '-' + str(uuid.uuid4())
    store_ext = filename_extension(new_file.filename)
    original_pic = store_base+'.'+store_ext
    # original_store_path = os.path.join("app\\static\\User_Images", store_base + "." + store_ext)
    # new_file.save(original_store_path)

    # Get the service client and upload to the s3 bucket
    s3 = boto3.client('s3', region_name='us-east-1')
    file_key_name = str(user_id) + '/' + original_pic
    s3.upload_fileobj(new_file, s3_bucketName, file_key_name, ExtraArgs={"ContentType": "image/jpeg"})

    try:
        cnx = get_db()
        cursor = cnx.cursor()

        # create a new tuple for the photo and store the
        query = "INSERT INTO photo (user_id) VALUES (%s)"
        cursor.execute(query, (user_id,))

        # get id of newly created tuple
        query = "SELECT LAST_INSERT_ID()"
        cursor.execute(query)

        row = cursor.fetchone()

        photo_id = row[0]
        # store the path to the original image
        query = "INSERT INTO storedphoto (filename,type_id,photo_id) VALUES (%s,%s,%s)"

        cursor.execute(query, (original_pic, TYPE_ORIGINAL, photo_id))

        # get the url of the upload image
        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': s3_bucketName, 'Key': file_key_name})

        # create thumbnail
        img = Image(file=urllib.request.urlopen(url))
        i = img.clone()
        i.resize(80, 80)
        bytes_io_file = BytesIO(i.make_blob('JPEG'))
        thumbail_pic = store_base+"_thumb."+store_ext
        # thumbnail_store_path = os.path.join("app\\static\\User_Images", store_base + "_thumb." + store_ext)
        # i.save(filename=thumbnail_store_path)
        # Get the service client and upload to the s3 bucket
        s3 = boto3.client('s3', region_name='us-east-1')
        file_key_name_thumb = str(user_id) + '/' + thumbail_pic
        s3.upload_fileobj(bytes_io_file, s3_bucketName, file_key_name_thumb,
                          ExtraArgs={"ContentType": "image/jpeg"})


        # store path to thumbnail
        query = "INSERT INTO storedphoto (filename,type_id,photo_id) VALUES (%s,%s,%s)"
        cursor.execute(query, (thumbail_pic, TYPE_THUMBNAIL, photo_id))

        # with open(original_store_path, 'rb') as f:
        #     image_bytes = f.read()
        di = img.clone()
        df_pic = store_base + "_df." + store_ext
        # df_store_path = os.path.join("app\\static\\User_Images", store_base + "_df." + store_ext)
        detect_faces_and_save(di, user_id, df_pic)

        query = "INSERT INTO storedphoto (filename,type_id,photo_id) VALUES (%s,%s,%s)"
        cursor.execute(query, (df_pic, TYPE_FACE_DETECTED, photo_id))

        cursor.close()

        cnx.commit()

    except Exception as e:
        raise e


@webapp.route('/api/upload', methods=['POST'])
def api_upload():
    if 'file' not in request.files:
        return "No file uploaded"

    if 'username' not in request.form or 'password' not in request.form:
        return "Authentication error (1)"

    cnx = get_db()
    cursor = cnx.cursor()
    query = "SELECT * FROM user WHERE username = %s"
    cursor.execute(query, (request.form['username'],))
    row = cursor.fetchone()

    if row is None:
        return "Authentication error (2)"

    user_id = row[0]
    hash = row[2]
    salt = row[3]

    password = request.form['password']

    salted_password = "{}{}".format(salt, password)
    m = hashlib.md5()
    m.update(salted_password.encode('utf-8'))
    new_hash = m.digest()

    if new_hash != hash:
        return "Authentication error (3)"

    new_file = request.files['file']

    # if user does not select file, browser also
    # submit a empty part without filename
    if new_file.filename == '':
        return "No file uploaded"

    if is_allowed_file(new_file.filename) == False:
        return "File not allowed"

    try:
        process_file(user_id, new_file)
    except Exception as e:
        return 'Unable to process file: ' + e

    return "OK"


def detect_faces_and_save(wand_img, user_id, filename):
    # imageBytes = numpy.asarray(bytearray(image_bytes), dtype=numpy.uint8)
    # image = cv2.imdecode(imageBytes, cv2.IMREAD_UNCHANGED)
    # image = cv2.imread(filename)
    img_buffer = numpy.asarray(bytearray(wand_img.make_blob()), dtype=numpy.uint8)
    image = cv2.imdecode(img_buffer, cv2.IMREAD_UNCHANGED)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(30, 30),
#        flags = cv2.cv.CV_HAAR_SCALE_IMAGE
        flags = cv2.CASCADE_SCALE_IMAGE
    )

    for (x, y, w, h) in faces:
        cv2.rectangle(image, (x, y), (x+w, y+h), (255, 255, 255), 2)

    r, outputImage = cv2.imencode('.jpg', image)
    if False==r:
        raise Exception('Error encoding image')

    img_stream = BytesIO(outputImage)

    # Get the service client and upload to the s3 bucket
    s3 = boto3.client('s3', region_name='us-east-1')
    file_key_name_df = str(user_id) + '/' + filename
    s3.upload_fileobj(img_stream, s3_bucketName, file_key_name_df,
                      ExtraArgs={"ContentType": "image/jpeg"})

