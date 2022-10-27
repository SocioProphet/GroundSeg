import json, subprocess, requests
from wireguard import Wireguard
from urbit_docker import UrbitDocker
from minio_docker import MinIODocker
from updater_docker import WatchtowerDocker
import socket
import time
import sys
import os

class Orchestrator:
    
    _urbits = {}
    _minios = {}
    _watchtower = {}
    minIO_on = False
    wireguard_reg = False
    app_status = 'live'
    gs_version = 'Beta-2.0.1'


    def __init__(self, config_file):
        # store config file location
        self.config_file = config_file

        # load existing or create new system.json
        self.config = self.load_config(config_file)

        # First boot setup
        if(self.config['firstBoot']):
            self.first_boot()
            self.config['firstBoot'] = False
            self.save_config()

        # get wireguard networking information
        # Load urbits with wg info
        # start wireguard
        self.wireguard = Wireguard(self.config)
        if('reg_key' in self.config.keys()):
           if(self.config['reg_key']!= None):
              self.wireguard_reg = True
              self.wireguard.stop()
              self.wireguard.start()

        self.load_urbits()

        # Start auto updater
        if not 'updateMode' in self.config:
           self.set_update_mode('auto')

        self._watchtower = WatchtowerDocker(self.config['updateMode'])

    def load_config(self, config_file):
        try:
            with open(config_file) as f:
                system_json = json.load(f)
                system_json['gsVersion'] = self.gs_version
                return system_json
        except Exception as e:
            print("creating new config file...")
            system_json = dict()
            system_json['firstBoot'] = True
            system_json['piers'] = []
            system_json['endpointUrl'] = "api.startram.io"
            system_json['apiVersion'] = "v1"
            system_json['gsVersion'] = self.gs_version
            system_json['updateMode'] = "auto"

            with open(config_file,'w') as f :
                json.dump(system_json, f)

            return system_json
            
    def wireguardStart(self):
        if(self.wireguard.wg_docker.isRunning()==False):
           self.wireguard.start()
           self.startMinIOs() 

    def wireguardStop(self):
        if(self.wireguard.wg_docker.isRunning() == True):
           for p in self._urbits.keys():
              if(self._urbits[p].config['network'] == 'wireguard'):
                 self.switchUrbitNetwork(p)
           self.stopMinIOs()
           self.wireguard.stop()


    def registerDevice(self, reg_key):
        self.config['reg_key'] = reg_key
        endpoint = self.config['endpointUrl']
        api_version = self.config['apiVersion']
        url = f'https://{endpoint}/{api_version}'
        x = self.wireguard.registerDevice(self.config['reg_key'], url) 
        time.sleep(2)
        self.anchor_config = self.wireguard.getStatus(url)
        print(self.anchor_config)
        if(self.anchor_config != None):
           print("starting wg")
           self.wireguard.start()
           self.wireguard_reg = True
           time.sleep(2)
           
           print("reg urbits")
           for p in self.config['piers']:
              self.registerUrbit(p)

           print("starting minIOs")
           self.startMinIOs()
           self.save_config()

           return 0
        return 1

    def getWireguardUrl(self):
        endpoint = self.config['endpointUrl']
        return endpoint

    def changeWireguardUrl(self, url):
        self.config['endpointUrl'] = url
        self.config['reg_key'] = ''
        self.wireguard_reg = False
        self.save_config()

        self.wireguardStop()

        return 0
        

    def load_urbits(self):
        for p in self.config['piers']:
            data = None
            with open(f'settings/pier/{p}.json') as f:
                data = json.load(f)

            self._urbits[p] = UrbitDocker(data)

            if data['minio_password'] != '':
                self._minios[p] = MinIODocker(data)
                self.startMinIOs()

    def update_mode(self):
        if "updateMode" in self.config:
            return self.config['updateMode']
        
        res = self.set_update_mode('install')
        
        if res == 0:
            return 'install'
        return ''

    def set_update_mode(self, mode):
        self.config['updateMode'] = mode
        self.save_config()

        self._watchtower.remove()
        self._watchtower = WatchtowerDocker(mode)

        return 0

    def registerMinIO(self, patp, password):
        self._urbits[patp].config['minio_password'] = password
        self._minios[patp] = MinIODocker(self._urbits[patp].config)
        self.minIO_on = True

        return 0

    def setMinIOEndpoint(self, patp):
        ak, sk = self._minios[patp].makeServiceAcc().split('\n')
        u = self._urbits[patp]

        endpoint = f"s3.{u.config['wg_url']}"
        bucket = 'bucket'
        lens_port = self.getLoopbackAddr(patp)
        access_key = ak.split(' ')[-1]
        secret = sk.split(' ')[-1]

        try:
            u.set_minio_endpoint(endpoint,access_key,secret,bucket,lens_port)
        except Exception as e:
            print(e)

    def getLoopbackAddr(self, patp):
        log = self.getLogs(patp).decode('utf-8').split('\n')[::-1]
        substr = 'http: loopback live on'

        for ln in log:
            if substr in ln:
                return str(ln.split(' ')[-1])

    def getMinIOSecret(self, patp):
        x = self._urbits[patp].config['minio_password']
        return(x)


    def startMinIOs(self):
      for m in self._minios.values():
         m.start()
      self.minIO_on = True

    def stopMinIOs(self):
      for m in self._minios.values():
         m.stop()
      self.minIO_on = False

    def registerUrbit(self, patp):
       endpoint = self.config['endpointUrl']
       api_version = self.config['apiVersion']
       url = f'https://{endpoint}/{api_version}'

       if self.wireguard_reg:
           self.anchor_config = self.wireguard.getStatus(url)
           patp_reg = False
           if(self.anchor_config != None):
              for ep in self.anchor_config['subdomains']:
                 if(patp in ep['url']):
                     print(f"{patp} already exists")
                     patp_reg = True

           if(patp_reg == False):

              self.wireguard.registerService(f'{patp}','urbit',url)
              self.wireguard.registerService(f's3.{patp}','minio',url)

           self.anchor_config = self.wireguard.getStatus(url)
           url = None
           http_port = None
           ames_port = None
           s3_port = None
           console_port = None


           print(self.anchor_config['subdomains'])
           pub_url = '.'.join(self.config['endpointUrl'].split('.')[1:])
           for ep in self.anchor_config['subdomains']:
               if(f'{patp}.{pub_url}' == ep['url']):
                   url = ep['url']
                   http_port = ep['port']
               elif(f'ames.{patp}.{pub_url}' == ep['url']):
                   ames_port = ep['port']
               elif(f'bucket.s3.{patp}.{pub_url}' == ep['url']):
                   s3_port = ep['port']
               elif(f'console.s3.{patp}.{pub_url}' == ep['url']):
                   console_port = ep['port']

           self._urbits[patp].setWireguardNetwork(url, http_port, ames_port, s3_port, console_port)
           self.wireguard.start()

    def addUrbit(self, patp, urbit):
        self.config['piers'].append(patp)
        self._urbits[patp] = urbit

        self.registerUrbit(patp)

        self.save_config()
        urbit.start()
        

    def removeUrbit(self, patp):
        urb = self._urbits[patp]
        urb.removeUrbit()
        urb = self._urbits.pop(patp)
        
        time.sleep(2)

        if(patp in self._minios.keys()):
           minio = self._minios[patp]
           minio.removeMinIO()
           minio = self._minios.pop(patp)

        self.config['piers'].remove(patp)
        self.save_config()


    def getUrbits(self):
        urbits= []

        for urbit in self._urbits.values():
            u = dict()
            u['name'] = urbit.pier_name
            u['running'] = urbit.isRunning();
            u['network'] = urbit.config['network']
            u['minio_registered'] = True

            if urbit.config['minio_password'] == '':
                u['minio_registered'] = False

            if self.wireguard_reg:
                u['s3_url'] = f"https://console.s3.{urbit.config['wg_url']}"
            else:
               u['s3_url'] = ""

            if(urbit.config['network']=='wireguard'):
                u['url'] = f"https://{urbit.config['wg_url']}"
            else:
                u['url'] = f'http://{os.environ["HOST_HOSTNAME"]}.local:{urbit.config["http_port"]}'

            urbits.append(u)

        return urbits

    def getCode(self,pier):
        code = ''
        addr = self.getLoopbackAddr(pier)
        try:
            code = self._urbits[pier].get_code(addr)
        except Exception as e:
            print(e)

        return code
    
    def has_bucket(self, patp):
        minio = list(self._minios.keys())
        for m in minio:
            if m == patp:
                return True
        return False

    def getContainers(self):
        minio = list(self._minios.keys())
        containers = list(self._urbits.keys())
        containers.append('wireguard')
        for m in minio:
            containers.append(f"minio_{m}")
        print(containers)
        return containers

    def switchUrbitNetwork(self, urbit_name):
        urbit = self._urbits[urbit_name]
        network = 'none'
        url = f"{socket.gethostname()}.local:{urbit.config['http_port']}"

        if((urbit.config['network'] == 'none') 
           and (self.wireguard_reg) 
           and (self.wireguard.wg_docker.isRunning())):
            network = 'wireguard'
            url = urbit.config['wg_url']

        urbit.setNetwork(network);
        time.sleep(2)
        

    def getOpenUrbitPort(self):
        http_port = 8080
        ames_port = 34343

        for u in self._urbits.values():
            if(u.config['http_port'] >= http_port):
                http_port = u.config['http_port']
            if(u.config['ames_port'] >= ames_port):
                ames_port = u.config['ames_port']

        return http_port+1, ames_port+1

    def getLogs(self, container):
        if container == 'wireguard':
            return self.wireguard.wg_docker.logs()
        if 'minio_' in container:
            return self._minios[container[6:]].logs()
        if container in self._urbits.keys():
            return self._urbits[container].logs()
        return ""


    def first_boot(self):
        subprocess.run("wg genkey > privkey", shell=True)
        subprocess.run("cat privkey| wg pubkey | base64 -w 0 > pubkey", shell=True)

        # Load priv and pub key
        with open('pubkey') as f:
           self.config['pubkey'] = f.read().strip()
        with open('privkey') as f:
           self.config['privkey'] = f.read().strip()
        #clean up files
        subprocess.run("rm privkey pubkey", shell =True)
   

    def save_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent = 4)