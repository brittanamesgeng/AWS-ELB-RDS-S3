import calendar

from flask import render_template, redirect, url_for, request, g
from app import webapp
import time

import boto3

import logging

from app import config
from app.config import db_config

from datetime import datetime, timedelta
from operator import itemgetter
import mysql.connector

max_threshold = 100
min_threshold = 10

increase_rate = 2
decrease_rate = 0.4

s3_bucketName = 'ece1779imagesstorage'
placementGroup_name = 'A2_workerpool_s'
targetGroupArn = 'arn:aws:elasticloadbalancing:us-east-1:530961352462:targetgroup/1779a2targetgroup/3e80dbe44f0607b6'

@webapp.route('/ec2_worker/create', methods=['POST'])
# Start a new EC2 instance
def ec2_create():

    # create connection to ec2
    ec2 = boto3.resource('ec2')

    instances = ec2.create_instances(ImageId=config.ami_id, InstanceType='t2.micro', MinCount=1, MaxCount=1,
                         Monitoring={'Enabled': True},
                         Placement={'AvailabilityZone': 'us-east-1c', 'GroupName': placementGroup_name},
                         SecurityGroups=['load-balancer-wizard-21'],
                         KeyName='ece1779_winter2019', TagSpecifications=[
                            {
                                'ResourceType': 'instance',
                                'Tags': [
                                    {
                                        'Key': 'Name',
                                        'Value': 'a2_additional_workers'
                                    },
                                ]
                            }, ])

    # register new instance to target group
    for instance in instances:
        instance.wait_until_running(
            Filters=[
                {
                    'Name': 'instance-id',
                    'Values': [
                        instance.id,
                    ]
                },
            ],
        )

        # print(instance.id)
        client = boto3.client('elbv2')
        client.register_targets(
            TargetGroupArn=targetGroupArn,
            Targets=[
                {
                    'Id': instance.id,
                },
            ]
        )

        # wait until finish
        waiter = client.get_waiter('target_in_service')
        waiter.wait(
            TargetGroupArn=targetGroupArn,
            Targets=[
                {
                    'Id': instance.id,
                },
            ],
        )

    return redirect(url_for('ec2_list'))


@webapp.route('/ec2_worker/delete/<id>', methods=['POST'])
# Terminate a EC2 instance
def ec2_destroy(id):

    ec2 = boto3.resource('ec2')

    ec2.instances.filter(InstanceIds=[id]).terminate()

    return redirect(url_for('ec2_list'))


@webapp.route('/ec2_worker', methods=['GET'])
# Display an HTML list of all ec2 instances
def ec2_list():

    # create connection to ec2
    ec2 = boto3.resource('ec2')

    # start instance which are stopped
    instances = ec2.instances.filter(
        Filters=[
            {'Name': 'placement-group-name',
             'Values': [placementGroup_name]
             },
            {'Name': 'instance-state-name',
             'Values': ['stopped']
             },
        ]
    )

    for instance in instances:
        ec2.instances.filter(InstanceIds=[instance.id]).start()


    instances = ec2.instances.filter(
        Filters=[{'Name': 'placement-group-name', 'Values': [placementGroup_name]}])

    # for instance in instances:
    #     print(instance.id, instance.image_id, instance.key_name, instance.tags)

    #Get current threshold settings to display
    # read from db
    cnx = get_db()
    cursor = cnx.cursor()
    query = '''SELECT min,max FROM threshold ORDER BY id DESC LIMIT 1'''
    cursor.execute(query, )
    row = cursor.fetchone()

    min_threshold_s = row[0]
    max_threshold_s = row[1]
    min_threshold = int(min_threshold_s)
    max_threshold = int(max_threshold_s)

    return render_template("workers/list.html", title="EC2 Instances", instances=instances, \
                           min_threshold = min_threshold, max_threshold = max_threshold)

@webapp.route('/ec2_worker/<id>', methods=['GET'])
# Display details about a specific instance.
def ec2_view(id):

    # print(id)
    ec2 = boto3.resource('ec2')

    # acquire an EC2 instance
    instance = ec2.Instance(id)

    # Create CloudWatch client
    client = boto3.client('cloudwatch')

    metric_name = 'CPUUtilization'
    namespace = 'AWS/EC2'
    statistic = 'Average'  # could be Sum,Maximum,Minimum,SampleCount,Average

    # get cpu statistics
    cpu = client.get_metric_statistics(
        Period=60,
        StartTime=datetime.utcnow() - timedelta(seconds=61 * 60),
        EndTime=datetime.utcnow() - timedelta(seconds=1 * 60),
        MetricName=metric_name,
        Namespace=namespace,  # Unit='Percent',
        Statistics=[statistic],
        Dimensions=[{'Name': 'InstanceId',
                     'Value': id}]

    )

    # gather return statistics
    cpu_stats = []
    for point in cpu['Datapoints']:
        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute
        # time = hour + minute/60

        time = hour + minute / 100
        time = round(time, 2)
        print(time)
        cpu_stats.append([time, point[statistic]])

    cpu_stats = sorted(cpu_stats, key=itemgetter(0))
    print(cpu_stats)

    # get request  statistic
    custom_metric_name = "http-request"
    namespace = 'EC2'
    statistic = 'Sum'  # could be Sum,Maximum,Minimum,SampleCount,Average

    requestrate = client.get_metric_statistics(
        Namespace = namespace,
        MetricName = custom_metric_name,
        Dimensions = [
            {'Name': 'InstanceId',
             'Value': id}
        ],
        StartTime=datetime.utcnow() - timedelta(minutes=1 * 30),
        EndTime=datetime.utcnow(),
        Period=60,
        Statistics=[statistic]
    )

    print(requestrate['Datapoints'])

    request_rate = []
    for point in requestrate['Datapoints']:

        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute

        print(point['Timestamp'])

        time = hour+minute/100
        time = round(time, 2)
        # print(str(minute) + "->" + str(point[statistic]))
        request_rate.append([time, point[statistic]])

    request_rate = sorted(request_rate, key=itemgetter(0))


    return render_template("workers/view.html", title="Instance Info",
                           instance=instance,
                           cpu_stats=cpu_stats,
                           request_rate=request_rate)


# connect the database
def connect_to_database():
    return mysql.connector.connect(user=db_config['user'],
                                   password=db_config['password'],
                                   host=db_config['host'],
                                   database=db_config['database'])


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = connect_to_database()
    return db


@webapp.teardown_appcontext
def teardown_db(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


@webapp.route('/s3/delete', methods=['POST'])
# delete all files in s3 bucket and the data in RDS
def delete():

    cnx = get_db()
    cursor = cnx.cursor()
    cursor.execute("""SET FOREIGN_KEY_CHECKS = 0""")
    cnx.commit()

    cnx = get_db()
    cursor = cnx.cursor()
    cursor.execute("""TRUNCATE table photo""")
    cnx.commit()

    cnx = get_db()
    cursor = cnx.cursor()
    cursor.execute("""TRUNCATE table user""")
    cnx.commit()

    cnx = get_db()
    cursor = cnx.cursor()
    cursor.execute("""SET FOREIGN_KEY_CHECKS = 1""")
    cnx.commit()

    cnx = get_db()
    cursor = cnx.cursor()
    cursor.execute("""TRUNCATE table storedphoto""")
    cnx.commit()

    s3 = boto3.resource('s3')
    bucket = s3.Bucket(s3_bucketName)

    keys = bucket.objects.all()

    for k in keys:
        image_name = k.key
        # print(image_name)
        s3.Object(s3_bucketName, image_name).delete()

    return redirect(url_for('s3_list'))


# save user setting
@webapp.route('/auto_manage', methods=['POST'])
def auto_manage():
    min_threshold = str(request.form.get('min_threshold'))
    print(min_threshold)

    max_threshold = str(request.form.get('max_threshold'))
    print(max_threshold)

    #save to sql
    cnx = get_db()
    cursor = cnx.cursor()
    query = "INSERT INTO threshold (min,max) VALUES (%s,%s)"
    cursor.execute(query, (min_threshold, max_threshold))
    cursor.close()
    cnx.commit()
    return redirect(url_for('ec2_list'))


@webapp.route('/manage_worker_pool', methods=['POST'])
def manage_worker_pool():

        # read from db
        cnx = get_db()
        cursor = cnx.cursor()
        query = '''SELECT min,max FROM threshold ORDER BY id DESC LIMIT 1'''
        cursor.execute(query,)
        row = cursor.fetchone()

        min_threshold_s =row[0]
        max_threshold_s =row[1]
        min_threshold = int(min_threshold_s)
        max_threshold = int(max_threshold_s)


        ec2 = boto3.resource('ec2')

        instances = ec2.instances.filter(
          Filters=[
              {'Name': 'placement-group-name',
               'Values': [placementGroup_name]
               },
              {'Name': 'instance-state-name',
               'Values': ['running']
               },
          ]
        )

        cpu_stats_1 = []
        ids = []

        for instance in instances:

            ids.append(instance.id)

            client = boto3.client('cloudwatch')

            # get cpu statistics in 1 minute(60s)

            cpu_1 = client.get_metric_statistics(
                Period=60,
                StartTime=datetime.utcnow() - timedelta(seconds=2 * 60),
                EndTime=datetime.utcnow() - timedelta(seconds=1 * 60),
                MetricName='CPUUtilization',
                Namespace='AWS/EC2',  # Unit='Percent',
                Statistics=['Average'],
                Dimensions=[{'Name': 'InstanceId',
                             'Value': instance.id}]
            )

            # gather return statistics

            for point in cpu_1['Datapoints']:
                load = round(point['Average'], 2)
                cpu_stats_1.append(load)

        if len(cpu_stats_1) == 0:
            average_load = 0
        else:
            average_load = sum(cpu_stats_1) / len(cpu_stats_1)

        # print log
        print(str(datetime.utcnow()) + ": " )
        print('average load: ' + str(average_load))
        print('cpu_stats_1: ' + str(cpu_stats_1))
        print("max_threshold: " + str(max_threshold))
        print("min_threshold: ", str(min_threshold))
        print("instance number: " + str(len(ids)))

        # Set up logging
        log = str(datetime.utcnow()) + ".log"
        logging.basicConfig(filename=log, level=logging.INFO)
        logging.info(str(datetime.utcnow()))
        logging.info('average load: ' + str(average_load))
        logging.info('cpu_stats_1: ' + str(cpu_stats_1))
        logging.info("max_threshold: " + str(max_threshold))
        logging.info("min_threshold: "+ str(min_threshold))
        logging.info("instance number: " + str(len(ids)))

    # option 1
        if average_load > max_threshold:
            # the number of new ec2 instances
            add_instance_num = int(len(cpu_stats_1) * (increase_rate-1)+1)
            print("add_instance_num: " + str(add_instance_num))

            # add instances
            for i in range(add_instance_num) :

                instances = ec2.create_instances(ImageId=config.ami_id, InstanceType='t2.micro', MinCount=1, MaxCount=1,
                                                 Monitoring={'Enabled': True},
                                                 Placement={'AvailabilityZone': 'us-east-1c',
                                                            'GroupName': placementGroup_name},
                                                 SecurityGroups=['load-balancer-wizard-21'],
                                                 KeyName='ece1779_winter2019', TagSpecifications=[
                        {
                            'ResourceType': 'instance',
                            'Tags': [
                                {
                                    'Key': 'Name',
                                    'Value': 'a2_additional_workers'
                                },
                            ]
                        }, ])


            # resize ELB
            for instance in instances:
                instance.wait_until_running(
                    Filters=[
                        {
                            'Name': 'instance-id',
                            'Values': [
                                instance.id,
                            ]
                        },
                    ],
                )

                # print(instance.id)
                client = boto3.client('elbv2')
                client.register_targets(
                    TargetGroupArn=targetGroupArn,
                    Targets=[
                        {
                            'Id': instance.id,
                        },
                    ]
                )


                # wait until finish
                waiter = client.get_waiter('target_in_service')
                waiter.wait(
                    TargetGroupArn= targetGroupArn,
                    Targets=[
                        {
                            'Id': instance.id,
                        },
                    ],
                )


    # option 2
        if average_load < min_threshold:
            minus_instance_num = int(len(cpu_stats_1) * (1-decrease_rate))
            print("minus_instance_num: " + str(minus_instance_num))

            if minus_instance_num > 0:
                ids_to_delete = ids[:minus_instance_num]
                print(ids_to_delete)

                #resize ELB
                for id in ids_to_delete:
                    # print(id)
                    client = boto3.client('elbv2')
                    client.deregister_targets(
                        TargetGroupArn=targetGroupArn,
                        Targets=[
                            {
                                'Id': id,
                            },
                        ]
                    )

                    # wait until finish
                    waiter = client.get_waiter('target_deregistered')
                    waiter.wait(
                        TargetGroupArn=targetGroupArn,
                        Targets=[
                            {
                                'Id': id,
                            },
                        ],

                    )

                # drop instances
                ec2 = boto3.resource('ec2')
                for id in ids_to_delete:
                    ec2.instances.filter(InstanceIds=[id]).terminate()

        return redirect(url_for('ec2_list'))
