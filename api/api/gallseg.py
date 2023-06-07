import json
import asyncio

from auth.auth import Auth

class GallSeg:
    def __init__(self,state):
        self.state = state

    async def handle(self, patp, action):
        print(f"gallseg:handle Receieved action from {patp}")
        print(action)
        try:
            ready = self.state.get('ready')
            config_ready = ready.get('config')
            orchestrator_ready = ready.get('orchestrator')
            if True: # if in list
                status_code = 1
                msg = "CONFIG_NOT_READY"
                token = None

                if config_ready:
                    # Verify the action
                    status_code, msg, token = Auth(self.state,urbit=patp).verify_session(action, patp)

                    '''
                    # process action in orchestrator
                    if status_code == 0:
                        if orchestrator_ready:
                            status_code, msg, token = self.handle_request(
                                    action,
                                    patp,
                                    status_code,
                                    msg,
                                    token
                                    )
                        else:
                            status_code = 1
                            msg = "ORCHESTRATOR_NOT_READY"
                    '''

                # make and send activity
                return self.make_activity(action.get('id'), status_code, msg, token)

        except Exception as e:
            print(f"gallseg:handle Error {e}")
    '''

    # receive action
    def handle_request(self, action, patp, status_code, msg, token):
        print(f"app:handle_request id: {action['id']}")
        try:
            # Get the action category
            cat = action.get('payload').get('category')

            # Does nothing
            if cat == "token":
                pass

            # System
            elif cat == "system":
                if patp in self.state['clients']['unauthorized']:
                    status_code, msg, token = self.system_action(action, patp, status_code, msg)
                elif patp in self.state['clients']['authorized']:
                    print(self.state['clients']['authorized'])

            elif cat == 'urbits':
                status_code, msg = self.orchestrator.ws_command_urbit(payload)

            elif cat == 'updates':
                status_code, msg = self.ws_command_updates(payload)

            elif cat == 'forms':
                status_code, msg = self.ws_command_forms(action)
            else:
                status_code = 1
                msg = "INVALID_CATEGORY"
                raise Exception(f"'{cat}' is not a valid category")
        except Exception as e:
            print(f"app:handle_request Error {e}")

        return status_code, msg, token

    # System
    def system_action(self, data, patp, status_code, msg):
        # hardcoded list of allowed modules
        whitelist = [
                'login',
                'startram',
                ]
        payload = data['payload']
        module = payload['module']
        action = payload['action']

        if module not in whitelist:
            raise Exception(f"{module} is not a valid module")

        if module == "login":
            status_code, msg, token = Auth(self.state).handle_login(data,
                                                                    patp,
                                                                    status_code,
                                                                    msg
                                                                    )

        if module == "startram":
            if action == "register":
                Thread(target=self.orchestrator.startram_register, args=(data['sessionid'],)).start()
            if action == "stop":
                Thread(target=self.orchestrator.startram_stop).start()
            if action == "start":
                Thread(target=self.orchestrator.startram_start).start()
            if action == "restart":
                Thread(target=self.orchestrator.startram_restart).start()
            if action == "endpoint":
                Thread(target=self.orchestrator.startram_change_endpoint,
                       args=(data['sessionid'],)
                       ).start()
            if action == "cancel":
                Thread(target=self.orchestrator.startram_cancel,
                       args=(data['sessionid'],)
                       ).start()

        return status_code, msg, token
        '''

    def make_activity(self, id, status_code, msg, token=None):
        res = {"activity":{id:{"message":msg,"status_code":status_code}}}
        if token:
            res['activity'][id]['token'] = token
        return json.dumps(res)