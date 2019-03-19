import urllib

from flask import render_template, session, request, redirect, url_for, g
import random
import hashlib
import boto3

from datetime import datetime, timedelta
from app import webapp
from app.db import get_db

custom_metric_name="http-request"
namespace = 'AWS/EC2'
statistic = 'Average'

s3_bucketName = 'ece1779imagesstorage'

@webapp.teardown_appcontext
def teardown_db(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@webapp.route('/logout', methods=['GET', 'POST'])
def logout():

    session.clear()
    return redirect(url_for('login'))


@webapp.route('/login', methods=['GET', 'POST'])
def login():

    # # send data to metric
    instance_id = urllib.request.urlopen('http://169.254.169.254/latest/meta-data/instance-id').read().decode()
    print(instance_id)

    print(datetime.utcnow());
    cwclient = boto3.client("cloudwatch")
    response = cwclient.put_metric_data(
        Namespace=namespace,
        MetricData=[
            {
                'MetricName': custom_metric_name,
                'Dimensions': [
                    {
                        'Name': 'InstanceId',
                        'Value': instance_id
                    },
                ],
                'Timestamp': datetime.utcnow(),
                'Value': 1.0,
                'Unit': 'None',
            },
        ]

    )
    print(response)

    uname = None
    e = None

    if 'username' in session:
        uname = session['username']

    if 'error' in session:
        e = session['error']
        session.pop('error')

    return render_template("users/login.html", error=e, username=uname)


@webapp.route('/login_submit', methods=['POST'])
def login_submit():
    if 'username' in request.form and 'password' in request.form:
        cnx = get_db()
        cursor = cnx.cursor()
        query = "SELECT * FROM user WHERE username = %s"
        cursor.execute(query, (request.form['username'],))
        row = cursor.fetchone()

        if row != None:
            hash = row[2]
            salt = row[3]

            password = request.form['password']

            salted_password = "{}{}".format(salt, password)
            m = hashlib.md5()
            m.update(salted_password.encode('utf-8'))
            new_hash = m.digest()

            if new_hash == hash:
                session['authenticated'] = True
                session['username'] = request.form['username']
                session['user_id'] = row[0]

                return redirect(url_for('thumbnails'))

    session['error'] = "Error! Incorrect username or password!"

    return redirect(url_for('login'))


@webapp.route('/new', methods=['GET', 'POST'])
def new_user():
    uname = None
    e = None

    if 'username' in session:
        uname = session['username']

    if 'error' in session:
        e = session['error']
        session.pop('error')

    return render_template("users/new.html", error=e, username=uname)

@webapp.route('/api/register', methods=['POST'])
def api_register():

    flag1 = 'username' in request.form
    flag2 = 'password' in request.form

    username = request.form['username']
    password = request.form['password']

    if 'username' not in request.form or 'password' not in request.form:
        return "Incomplete data"

    username = request.form['username']
    password = request.form['password']

    try:
        create_user(username, password)
    except Exception as e:
        return "Error: " + e

    return "OK"

@webapp.route('/new_submit', methods=['POST'])
def new_user_submit():
    if 'username' not in request.form or 'password' not in request.form:
        if 'username' in request.form:
            session['username'] = request.form['username']

        session['error'] = "Missing username or password"

        return redirect(url_for('new_user'))

    username = request.form['username']
    password = request.form['password']

    try:
        create_user(username, password)
    except Exception as e:
        session['error'] = str(e)
        return redirect(url_for('new_user'))

    return redirect(url_for('login'))


def create_user(username, password):
    cnx = get_db()
    cursor = cnx.cursor()
    query = "INSERT INTO user (username,hash,salt) VALUES (%s,%s,%s)"
    salt = str(random.getrandbits(16))
    salted_password = "{}{}".format(salt, password)
    m = hashlib.md5()
    m.update(salted_password.encode('utf-8'))
    hash = m.digest()
    cursor.execute(query, (username, hash, salt))
    cursor.close()
    cnx.commit()
