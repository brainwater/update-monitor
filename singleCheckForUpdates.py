#!/usr/bin/python3

# Depends on apt package update-notifier-common (for '/usr/lib/update-notifier/apt-check') and apt packeage python3-paho-mqtt

import os
import sys
import subprocess
import json
import socket
import time
import paho.mqtt.client as mqtt

UPDATE_DELAY = 60*30

secrets_path = "/etc/homeassistant/secrets.json"

if not os.path.isfile(secrets_path):
    raise SystemExit("Error! No file found at " + secrets_path + " unable to send!")

with open(secrets_path) as sfile:
    secrets = json.load(sfile)

def init_mqtt_client(username, password, broker, port):
    mqtt_client = mqtt.Client(socket.gethostname())
    mqtt_client.username_pw_set(username, password=password)
    mqtt_client.connect(broker, port)
    return mqtt_client

def getTopic(sensorType, postfix="/state", prefix=socket.gethostname()):
    return "homeassistant/binary_sensor/" + prefix + sensorType + postfix
    

def advertise(mqtt_client):
    topic = getTopic("update", "/config")
    payload = {
        "name": socket.gethostname() + " Updates Available",
        "device_class": "update",
        "state_topic": getTopic("update"),
        "expire_after": UPDATE_DELAY * 3,
        "unique_id": socket.gethostname() + "update",
        "value_template": "{{ value_json.state }}"
    }
    pub(mqtt_client, topic, json.dumps(payload))
    print("Advertised")

def sendvalue(mqtt_client, num_updates: int):
    val = "OFF"
    if num_updates > 0:
        val = "ON"
    payload = {"state": val}
    topic = getTopic("update")
    pub(mqtt_client, topic, json.dumps(payload))
    print("Sent value")

def pub(mqtt_client, topic, output):
    retval = mqtt_client.publish(topic, output)
    if retval.rc == mqtt.MQTT_ERR_NO_CONN:
        mqtt_client.reconnect()
    
mqtt_client = init_mqtt_client(
    username=secrets['mqtt_username'],
    password=secrets['mqtt_password'],
    broker=secrets['mqtt_broker'],
    port=secrets['mqtt_port'])

dir_path = os.path.dirname(os.path.realpath(__file__))
blarg_path = os.path.join(dir_path, "blarg.py")
apt_check_output = subprocess.check_output(blarg_path, stderr=subprocess.STDOUT).decode('utf-8')
output_lst = apt_check_output.split(";")
num_updates, num_security = int(output_lst[0]), output_lst[1]

advertise(mqtt_client)
sendvalue(mqtt_client, num_updates)
