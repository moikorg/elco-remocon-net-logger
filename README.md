# Elco Remocon-net data logger

This Python script gets the data from the heatpump system via the Elco Remocon-Net cloud service.

The data will be published via MQTT and logged in a MySQL/MariaDB. The configuration information
must be added in a config file.

## config.rc
```sh
[MQTT]
host = localhost
username = ... 
password = ...
client_name = ...

[DB]
host = localhost
username = ...
password = ...
db = elco
port = 3306

[REMOCON-NET]
url = https://www.remocon-net.remotethermo.com/
username = ...
password = ...
