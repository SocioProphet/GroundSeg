try:
    import sys
    dev = sys.argv[1] == "dev"
except:
    dev = False

# GroundSeg modules
from config import Config
#from orchestrator import Orchestrator

# Flask apps
from groundseg_flask import GroundSeg
from c2c_flask import C2C

# Threads
from threading import Thread
from binary_updater import BinUpdater
from docker_updater import DockerUpdater
from system_monitor import SysMonitor
from linux_updater import LinuxUpdater
from melder import Melder
from anchor_information import AnchorUpdater
from wireguard_refresher import WireguardRefresher
from kill_switch import KillSwitch
from keygen import KeyGen

# Setup System Config
base_path = "/opt/nativeplanet/groundseg"
sys_config = Config(base_path, dev)

# Start Updater
bin_updater = BinUpdater(sys_config, sys_config.debug_mode)
Thread(target=bin_updater.check_bin_update, daemon=True).start()

# Check C2C
if sys_config.device_mode == "c2c":
    # C2C kill switch
    ks = KillSwitch(sys_config)
    Thread(target=ks.kill_switch, daemon=True).start()

    # Flask
    c2c = C2C(sys_config)
    c2c.run()

else:
    '''
    # System monitoring
    sys_mon = SysMonitor(sys_config)
    Thread(target=sys_mon.ram_monitor, daemon=True).start()
    Thread(target=sys_mon.cpu_monitor, daemon=True).start()
    Thread(target=sys_mon.temp_monitor, daemon=True).start()
    Thread(target=sys_mon.disk_monitor, daemon=True).start()

    # Start Key Generator
    gen = KeyGen(sys_config)
    Thread(target=gen.generator_loop, daemon=True).start()

    # Linux updater
    if sys_config.device_mode == "npbox":
        apt_cmd = LinuxUpdater(sys_config, ws_util)
        Thread(target=apt_cmd.run, daemon=True).start()


    # Scheduled melds
    meld_loop = Melder(sys_config, orchestrator)
    Thread(target=meld_loop.meld_loop, daemon=True).start()

    # Anchor information
    anchor_loop = AnchorUpdater(sys_config, orchestrator)
    Thread(target=anchor_loop.anchor_loop, daemon=True).start()

    # Wireguard connection refresher
    wg_refresher = WireguardRefresher(sys_config, orchestrator)
    Thread(target=wg_refresher.refresh_loop, daemon=True).start()

    # Docker updater
    docker_updater = DockerUpdater(sys_config, orchestrator)
    Thread(target=docker_updater.check_docker_update, daemon=True).start()

    '''
    # Websocket Util
    from ws_util import WSUtil
    ws_util = WSUtil(sys_config)

    # Orchestrator
    from orchestrator import Orchestrator
    orchestrator = Orchestrator(sys_config, ws_util, dev)

    # Websocket API
    from websocket_handler import API
    api = API(sys_config, ws_util, orchestrator)
    api.run()

    '''
    # Flask
    groundseg = GroundSeg(sys_config, orchestrator, ws_util)
    groundseg.run()
    '''