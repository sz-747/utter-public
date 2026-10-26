"""
LLM role loader

Features:
1. Loads every role in the LLM/ folder automatically
2. Reads the role settings from each module
3. Error handling and validation
"""

import sys
from pathlib import Path
from typing import Dict
from util.llm.llm_role_config import RoleConfig


class RoleLoader:
    """Role loader"""

    def __init__(self):
        self.roles_registry: Dict[str, RoleConfig] = {}
        from config_client import BASE_DIR
        self.llm_dir = Path(BASE_DIR) / 'LLM'
        self.load_all_roles()

    def register_role(self, module_name: str, module) -> str:
        """Register a role from a module

        Returns:
            The role name
        """
        from dataclasses import fields

        # 1. Take every named field from RoleConfig
        config = {'module_name': module_name}
        for f in fields(RoleConfig):
            if f.name == 'module_name':
                continue
            # Read the variable if the module (role script) defines it
            if hasattr(module, f.name):
                config[f.name] = getattr(module, f.name)
            # Otherwise leave it out so RoleConfig uses the dataclass default

        # 2. Create the RoleConfig
        role_config = RoleConfig(**config)

        # An empty name and the default role name both mean the default role
        role_name = role_config.name or RoleConfig.DEFAULT_ROLE_NAME

        self.roles_registry[role_name] = role_config

        return role_name

    def load_all_roles(self):
        """Load all roles"""
        self.roles_registry.clear()
        errors = []

        for file_path in sorted(self.llm_dir.glob('*.py')):
            if file_path.name == '__init__.py':
                continue

            try:
                module_name = f"LLM.{file_path.stem}"

                if module_name in sys.modules:
                    del sys.modules[module_name]

                module = __import__(module_name, fromlist=[''])

                if not hasattr(module, 'provider') or not hasattr(module, 'model'):
                    errors.append({
                        'file': file_path.name,
                        'error': 'Missing required fields',
                        'details': 'provider or model is missing'
                    })
                    continue

                self.register_role(module_name, module)

            except SyntaxError as e:
                errors.append({
                    'file': file_path.name,
                    'error': 'Syntax error',
                    'details': f"Line {e.lineno}: {e.msg}"
                })
            except Exception as e:
                errors.append({
                    'file': file_path.name,
                    'error': type(e).__name__,
                    'details': str(e)
                })

        return errors

    def reload_role(self, file_path: str):
        """Reload one role"""
        try:
            file_path = Path(file_path)

            if file_path.suffix != '.py' or file_path.name == '__init__.py':
                return False, "Not a role file"

            module_name = f"LLM.{file_path.stem}"

            if module_name in sys.modules:
                del sys.modules[module_name]

            module = __import__(module_name, fromlist=[''])

            if not hasattr(module, 'provider') or not hasattr(module, 'model'):
                return False, "Missing required fields"

            self.register_role(module_name, module)

            return True, None

        except SyntaxError as e:
            return False, f"Syntax error (line {e.lineno}): {e.msg}"
        except Exception as e:
            return False, f"{type(e).__name__}: {str(e)}"

    def get_roles(self) -> Dict[str, RoleConfig]:
        """Return all roles"""
        return self.roles_registry.copy()

    def get_default_role(self) -> RoleConfig:
        """Return the default role"""
        return self.roles_registry.get(RoleConfig.DEFAULT_ROLE_NAME, RoleConfig(name=RoleConfig.DEFAULT_ROLE_NAME, module_name='', process=False))

    def get_role_by_name(self, name: str) -> RoleConfig:
        """Return a role by name"""
        return self.roles_registry.get(name, RoleConfig(name=RoleConfig.DEFAULT_ROLE_NAME, module_name='', process=False))
