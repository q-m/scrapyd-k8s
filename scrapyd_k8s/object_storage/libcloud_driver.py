import os

from libcloud.storage.types import ObjectError, ContainerDoesNotExistError, ObjectDoesNotExistError, InvalidContainerNameError
from libcloud.storage.providers import get_driver

class LibcloudObjectStorage:

    def __init__(self, config):
        self._region = config.scrapyd().get('aws_region')
        self._access_key_id = config.scrapyd().get('aws_access_key_id')
        self._secret_access_key = config.scrapyd().get('aws_secret_access_key')
        self._container_name = config.scrapyd().get('aws_bucket_name')
        self._storage_provider = config.scrapyd().get('storage_provider')

        if self._region is None or self._access_key_id is None or self._secret_access_key is None:
            raise ValueError('AWS credentials not set')
        if self._container_name is None:
            raise ValueError('Bucket name not set')

        driver_class = get_driver(self._storage_provider)
        self.driver = driver_class(self._access_key_id, self._secret_access_key, region=self._region)

    def upload_file(self, local_path: str):
        object_name = os.path.basename(local_path)
        container = self.driver.get_container(container_name=self._container_name)
        file_path = local_path
        try:
            self.driver.upload_object(file_path, container, object_name, extra=None, verify_hash=True, headers=None)
        except ObjectError as e:
            print(f"Error uploading the file '{object_name}': {e}")

    def is_local_file_uploaded(self, local_path: str):
        object_name = os.path.basename(local_path)
        object_from_storage = None
        try:
            object_from_storage = self.driver.get_object(container_name=self._container_name, object_name=object_name)
            if object_from_storage is not None:
                return True
        except ObjectDoesNotExistError:
            return False
        except ContainerDoesNotExistError as e:
            print(f"Container with the name '{self._container_name}' does not exist in the cloud storage")
        except InvalidContainerNameError as e:
            print(f"Invalid container name '{self._container_name}'")
        finally:
            return False
