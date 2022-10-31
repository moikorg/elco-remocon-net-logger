FROM python:3.10-alpine

#RUN apk update && apk upgrade && apk add bash 
#RUN apk add python3 python3-dev py3-pip  mariadb-dev build-base
#RUN pip install --upgrade pip
#RUN pip install mysqlclient 
#RUN apk add mariadb-client-libs

#RUN apk add mariadb-connector-c-dev mariadb-connector-c

#run apk add py3-sqlalchemy 
#RUN apk del python3-dev mariadb-dev build-base 


#RUN rm -rf /var/cache/apk/*

RUN mkdir /code
WORKDIR /code
ADD code/requirements.txt /code/
RUN pip3 install -r requirements.txt
ADD code/* /code/
ENTRYPOINT ["python3"]
CMD ["HVAC_Sensor.py"]
