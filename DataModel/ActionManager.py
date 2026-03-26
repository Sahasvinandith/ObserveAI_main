import os
import json
import numpy as np

class ActionManager:
    """
    Manages custom assigned Actions.
    Reads and writes reference pose data (.json) files to the Actions_db folder.
    """
    def __init__(self, db_path="Actions_db"):
        self.db_path = db_path
        os.makedirs(self.db_path, exist_ok=True)
        self.actions = {}  # In-memory cache of loaded actions
        self.load_all_actions()

    def load_all_actions(self):
        """Loads all action config and reference data from Actions_db"""
        self.actions.clear()
        if not os.path.exists(self.db_path):
            return

        for filename in os.listdir(self.db_path):
            if filename.endswith(".json"):
                action_name = filename[:-5]
                filepath = os.path.join(self.db_path, filename)
                try:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                        self.actions[action_name] = data
                        print(f"[ACTION MANAGER] Loaded action '{action_name}'")
                except Exception as e:
                    print(f"[ACTION MANAGER] Error loading {filename}: {e}")

    def save_action(self, action_name: str, pose_data: dict):
        """Saves a new action's reference pose data to disk"""
        filepath = os.path.join(self.db_path, f"{action_name}.json")
        try:
            with open(filepath, 'w') as f:
                json.dump(pose_data, f, indent=4)
            self.actions[action_name] = pose_data
            print(f"[ACTION MANAGER] Saved action '{action_name}'")
            return True
        except Exception as e:
            print(f"[ACTION MANAGER] Error saving action '{action_name}': {e}")
            return False

    def get_action_list(self):
        """Returns a list of all custom action names"""
        return list(self.actions.keys())

    def get_action_data(self, action_name: str):
        """Returns the specific reference pose data for an action"""
        return self.actions.get(action_name, None)

    def delete_action(self, action_name: str):
        """Deletes an action from the database"""
        filepath = os.path.join(self.db_path, f"{action_name}.json")
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                if action_name in self.actions:
                    del self.actions[action_name]
                print(f"[ACTION MANAGER] Deleted action '{action_name}'")
                return True
            except Exception as e:
                print(f"[ACTION MANAGER] Error deleting action '{action_name}': {e}")
                return False
        return False
