
class Broadcaster:
    def __init__(self,state):
        self.state = state
        self.structure = self.state['broadcast']

    # Broadcast action for System and Updates
    def system_broadcast(self, category, module, action, info=""):
        try:
            # Whitelist of categories allowed to broadcast
            whitelist = ['system','updates']
            if category not in whitelist:
                raise Exception(f"Error. Category '{category}' not in whitelist")

            # Category
            try:
                if not self.structure.get(category) or not isinstance(self.structure[category], dict):
                    self.structure[category] = {}
            except Exception as e:
                raise Exception(f"failed to set category '{category}': {e}") 

            # Module
            try:
                if not self.structure[category].get(module) or not isinstance(self.structure[category], dict):
                    self.structure[category][module] = {}
            except Exception as e:
                raise Exception(f"failed to set module '{module}': {e}") 

            # Action
            self.structure[category][module][action] = info

        except Exception as e:
            print(f"broadcaster:system-broadcast {e}")
            return False

        return True

    # Broadcast action for Urbits
    def urbit_broadcast(self, patp, module, action, info=""):
        try:
            # Set root to structure
            root = self.structure
            # Category
            if not self.structure.get('urbits') or not isinstance(self.structure['urbits'], dict):
                self.structure['urbits'] = {}

            # Set root to urbits
            root = root['urbits']
            # Patp
            if not root.get(patp) or not isinstance(root[patp], dict):
                root[patp] = {}

            # Set root to patp
            root = root[patp]
            # Module
            if not root.get(module) or not isinstance(root[module], dict):
                root[module] = {}

            # Set root to patp
            root = root[module]
            # Action
            root[action] = info

        except Exception as e:
            print(f"broadcaster:urbit-broadcast {e}")
            return False
        return True