import requests
import json
import re
import os
import datetime
import configparser
import paho.mqtt.client as mqtt
from peewee import *
from urllib.parse import quote
import argparse
from time import strftime, gmtime, sleep
import schedule
import sys
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS



db = MySQLDatabase(None)  # will be initialized later

## DB models
class BaseModel(Model):
    """A base model that will use the MariaDB"""
    class Meta:
        database = db


class HVAC_Model(BaseModel):
    class Meta:
        table_name = 'hvac'

    id = AutoField(primary_key=True)
    ts = DateTimeField()
    ts_epoch = TimestampField()
    outside_temp = FloatField()
    water_temp = FloatField()
    heat_pump_state = CharField(max_length=5)


def parse_args() -> object:
    parser = argparse.ArgumentParser(description='Reads values from Elco Remocon-Net API and writes it to MQTT and DB')
    parser.add_argument('-f', help='path and filename of the config file, default is ./config.rc',
                        default='config.rc')
    parser.add_argument('-d', help='write the data also to MariaDB/MySQL DB', action='store_true', dest='db_write')
    return parser.parse_args()


def on_connect(client, userdata, flags, rc):
    #print("Connected with result code "+str(rc))
    pass


def on_publish(client, userdata, result):
    #print("Data published")
    pass

def on_disconnect(client, userdata, rc):
    #print("disconnecting reason  " + str(rc))
    pass


def connectMQTT(conf):
    broker = conf['host']
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_publish = on_publish
    client.on_disconnect = on_disconnect
    client.username_pw_set(username=conf['username'],
                           password=conf['password'])
    try:
        client.connect(broker, 1883, 60)
    except:
        print("ERROR: Can not connect to MQTT broker")
        return -1
    return client


def writeHVACMQTT(conf, ep, waterTemp, outsideTemp, heatpump):
    #print("Write MQTT")
    client = connectMQTT(conf)
    if client == -1:
        return -1

    mqtt_json = "{\"ts\":\"" + str(ep) + "\"," + \
                "\"waterTemp\":" + str(waterTemp) + "," + \
                "\"outsideTemp\":" + str(outsideTemp) + "," + \
                "\"heatPumpState\":\"" + heatpump + "\"}"
    client.publish("sensor/hvac/1", mqtt_json)  # publish
    client.disconnect()


def config_section_map(conf, section):
    dict1 = {}
    options = conf.options(section)
    for option in options:
        try:
            dict1[option] = conf.get(section, option)
            if dict1[option] == -1:
                print("skip: %s" % option)
        except:
            print("exception on %s!" % option)
            dict1[option] = None
    return dict1


def read_config(conf, config_file):
    try:
        c_mqtt = config_section_map(conf, "MQTT")
    except:
        print("Could not open conf file, or could not find the MQTT conf section in the file")
        config_full_path = os.getcwd() + "/" + config_file
        print("Tried to open the conf file: ", config_full_path)
        raise ValueError
    try:
        c_db = config_section_map(conf, "DB")
    except:
        print("Could not find the DB conf section")
        config_full_path = os.getcwd() + "/" + config_file
        print("Tried to open the conf file: ", config_full_path)
        raise ValueError
    try:
        c_alert_sensor = config_section_map(conf, "REMOCON-NET")
    except:
        print("Could not find the REMOCON-NET conf section")
        config_full_path = os.getcwd() + "/" + config_file
        print("Tried to open the conf file: ", config_full_path)
        raise ValueError
    try:
        c_influxdb = config_section_map(conf, "InfluxDB")
    except:
        print("Could not find the InfluxDB conf section")
        config_full_path = os.getcwd() + "/" + config_file
        print("Tried to open the conf file: ", config_full_path)
        raise ValueError
    return (c_mqtt, c_db, c_alert_sensor, c_influxdb)


def write2InfluxDB(conf, water_tmp, outside_tmp, heating_state):
    with InfluxDBClient(conf['url'], token=conf['token'], org=conf['org']) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)

        #heating_state_bool = True if heating_state == 'on' else False
        ts = strftime("%Y-%m-%d %H:%M:%S", gmtime())
        p = Point(conf['measurement'])\
            .tag("location", conf['location'])\
            .time(ts)\
            .field("temp_outside", outside_tmp)\
            .field("temp_water", water_tmp)\
            .field("heatpump_state", heating_state)
        write_api.write(bucket=conf['bucket'], org=conf['org'], record=p)



def job(conf_mqtt, conf_hvac, conf_influxdb, write_db):
    base_url = conf_hvac['url']
    url = base_url + "R2/Account/Login?returnUrl=%2FR2%2FHome"
    payload = "Email="+quote(conf_hvac['username'], safe='')+"&Password="+quote(conf_hvac['password'], safe='')+"&RememberMe=false"
    headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Cookie': 'browserUtcOffset=-120'}
    session = requests.session()

    # login,get session cookie and address for json data
    response = session.post(url=url, headers=headers, data=payload, allow_redirects=True)
    m = re.search(r"gatewayId: \'(.*)\'", response.text)
    try:
        gatewayID = m.group(1)
    except:
        print("didn't get the gatewayID from the current request, trying later")
        return
    url = f"{base_url}R2/PlantHomeBsb/GetData/{gatewayID}"
    # get json data
    send_json = {"useCache": "true", "zone": "1", "filter": {"progIds": "null", "plant": "true", "zone": "true"}}

    response = session.post(url=url, json=send_json)
    try:
        result_json = json.loads(response.text)
    except:
        print("could not decode json")
        return
    # extract the interesting data from the json
    try:
        heatpump_data = result_json['data']
        water_temp = heatpump_data['plantData']['dhwStorageTemp']
        outside_temp = heatpump_data['plantData']['outsideTemp']
        heatPump_str = 'off'
        if heatpump_data['plantData']['heatPumpOn']:
             heatPump_str = 'on'
    except KeyError:
        print("couldn't find a key, trying later on")
        return
    now = datetime.datetime.now()
    ep = now.strftime('%Y-%m-%d %H:%M:%S')
    print("TS: "+ep+", WaterTemp: "+str(water_temp)+", OutsideTemp: "+str(outside_temp)+", HeatPumpState: "+heatPump_str)

    writeHVACMQTT(conf=conf_mqtt, ep=ep, waterTemp=water_temp, outsideTemp=outside_temp, heatpump=heatPump_str)
    write2InfluxDB(conf_influxdb, water_temp, outside_temp, heatPump_str)
    if write_db:
        HVAC_Model.insert(ts=ep,ts_epoch=now, outside_temp=outside_temp, water_temp=water_temp, heat_pump_state=heatPump_str).execute()


def main(config, db_write):
    try:
        (conf_mqtt, conf_db, conf_hvac, conf_influxdb) = read_config(config, args.f)
    except ValueError:
        exit(1)
    if db_write:
        db.init(conf_db['db'], host=conf_db['host'], user=conf_db['username'], password=conf_db['password'],
                port=int(conf_db['port']))
        try:
            db.connect(conf_db)
        except:
            print("Could not connect to DB, exiting")
            exit(-1)

    try:
        periodicity = int(conf_hvac['periodicity'])
    except:
        sys.exit("Periodicity value must be int")

    schedule.every(periodicity).seconds.do(job, conf_mqtt=conf_mqtt, conf_hvac=conf_hvac, conf_influxdb=conf_influxdb, write_db=db_write)
    while True:
        schedule.run_pending()
        sleep(5)

    if db_write:
        db.close() 



if __name__ == '__main__':
    args = parse_args()
    config = configparser.ConfigParser()
    config.read(args.f)

    main(config, args.db_write)
