import os
import logging

logger = logging.getLogger(__name__)

from libcloud.storage.types import ObjectError, ContainerDoesNotExistError, ObjectDoesNotExistError, InvalidContainerNameError
from libcloud.storage.providers import get_driver

class LibcloudObjectStorage:

    def __init__(self, config):
        self._storage_provider = config.joblogs().get('storage_provider')
        if self._storage_provider is None:
            logger.error('Storage provider is not defined in the configuration.')
            raise ValueError('Storage provider is not defined')

        self._container_name = config.joblogs().get('container_name')
        if self._container_name is None:
            logger.error('Container name is not set in the configuration.')
            raise ValueError('Container name is not set')

        args_envs = config.joblogs_provider_args(self._storage_provider)
        args = {}
        for arg, env in args_envs.items():
            env_value = os.getenv(env)
            if env_value is None:
                logger.error(f"Environment variable '{env}' for argument '{arg}' is not set.")
                raise ValueError(f"Environment variable '{env}' for argument '{arg}' is not set.")
            args[arg] = env_value

        driver_class = get_driver(self._storage_provider)
        print("CLOUD CREDENTIALS")
        print(args)
        try:
            self.driver = driver_class(**args)
            logger.info(f"Initialized driver for storage provider '{self._storage_provider}'.")
        except Exception as e:
            logger.exception(f"Failed to initialize driver for storage provider '{self._storage_provider}'.")
            raise

    def upload_file(self, local_path: str):
        object_name = os.path.basename(local_path)
        try:
            container = self.driver.get_container(container_name=self._container_name)
            self.driver.upload_object(
                local_path,
                container,
                object_name,
                extra=None,
                verify_hash=True,
                headers=None
            )
            logger.info(f"Successfully uploaded '{object_name}' to container '{self._container_name}'.")
        except (ObjectError, ContainerDoesNotExistError, InvalidContainerNameError) as e:
            logger.exception(f"Error uploading the file '{object_name}': {e}")
        except Exception as e:
            logger.exception(f"An unexpected error occurred while uploading '{object_name}': {e}")

    def is_local_file_uploaded(self, local_path: str) -> bool:
        object_name = os.path.basename(local_path)
        try:
            self.driver.get_object(
                container_name=self._container_name,
                object_name=object_name
            )
            logger.debug(f"Object '{object_name}' exists in container '{self._container_name}'.")
            return True
        except ObjectDoesNotExistError:
            logger.debug(f"Object '{object_name}' does not exist in container '{self._container_name}'.")
            return False
        except ContainerDoesNotExistError:
            logger.error(f"Container '{self._container_name}' does not exist in the cloud storage.")
            return False
        except InvalidContainerNameError:
            logger.error(f"Invalid container name '{self._container_name}'.")
            return False
        except Exception as e:
            logger.exception(f"An unexpected error occurred while checking for object '{object_name}': {e}")
            return False
