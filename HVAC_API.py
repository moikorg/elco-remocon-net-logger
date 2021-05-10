import requests
import json
import re
import os
import datetime
import configparser
import paho.mqtt.client as mqtt
from peewee import *
from urllib.parse import quote


db = MySQLDatabase(None)  # will be initialized later
#db = SqliteDatabase(':memory:')

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

def on_connect(client, userdata, flags, rc):
    print("Connected with result code "+str(rc))


def on_publish(client, userdata, result):
    print("Data published")
    pass

def on_disconnect(client, userdata, rc):
    print("disconnecting reason  " + str(rc))


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
    print("Write MQTT")
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
        print("Could not find the ALERT_SENSOR conf section")
        config_full_path = os.getcwd() + "/" + config_file
        print("Tried to open the conf file: ", config_full_path)
        raise ValueError
    return (c_mqtt, c_db, c_alert_sensor)



def main(conf_mqtt, conf_hvac ):
    base_url = conf_hvac['url']
    url = base_url + "Account/Login?returnUrl=HTTP/2"
    payload = "Email="+quote(conf_hvac['username'], safe='')+"&Password="+quote(conf_hvac['password'], safe='')+"&RememberMe=false"
    headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Cookie': 'browserUtcOffset=-120'}
    session = requests.session()

    # login,get session cookie and address for json data
    response = session.post(url=url, headers=headers, data=payload)
    m = re.search(r"\'(/BsbPlantDashboard/GetPlantData/.*)\'", response.text)
    url = base_url + m.group(0)[1:-1]

    # get json data
    response = session.get(url=url)
    heatpump_data = json.loads(response.text)

    # extract the interesting data from the json
    water_temp = heatpump_data["dhwStorageTemp"]
    outside_temp = heatpump_data['outsideTemp']
    heatPump_str = 'off'
    if heatpump_data['heatPumpOn'] == 'True':
        heatPump_str = 'on'

    now = datetime.datetime.now()
    ep = now.strftime('%Y-%m-%d %H:%M:%S')
    print("TS: "+ep+", WaterTemp: "+str(water_temp)+", OutsideTemp: "+str(outside_temp)+", HeatPumpState: "+heatPump_str)

    writeHVACMQTT(conf=conf_mqtt, ep=ep, waterTemp=water_temp, outsideTemp=outside_temp, heatpump=heatPump_str)
    HVAC_Model.insert(ts=ep,ts_epoch=now, outside_temp=outside_temp, water_temp=water_temp, heat_pump_state=heatPump_str).execute()




if __name__ == '__main__':
    config = configparser.ConfigParser()
    config.read('config.rc')
    try:
        (conf_mqtt, conf_db, conf_hvac, ) = read_config(config, 'config.rc')
    except ValueError:
        exit(1)
    db.init(conf_db['db'], host=conf_db['host'], user=conf_db['username'], password=conf_db['password'],
            port=int(conf_db['port']))
    db.connect(conf_db)
    #db.create_tables([HVAC_Model])

    main(conf_mqtt, conf_hvac)
    db.close()
    print("finishing")
