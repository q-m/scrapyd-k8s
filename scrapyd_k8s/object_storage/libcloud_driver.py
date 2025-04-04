import os
import re
import logging

from libcloud.storage.types import (
    ObjectError,
    ContainerDoesNotExistError,
    InvalidContainerNameError,
)
from libcloud.storage.providers import get_driver
from scrapyd_k8s.object_storage.log_compressor import Compression

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

class LibcloudObjectStorage:
    """
    A class to interact with cloud object storage using Apache Libcloud.

    ...

    Attributes
    ----------
    driver : libcloud.storage.base.StorageDriver
        An instance of the storage driver for the specified provider.
    _storage_provider : str
        The storage provider name (e.g., 's3' for Amazon S3).
    _container_name : str
        The name of the container (bucket) in the storage provider.
    VARIABLE_PATTERN : re.Pattern
        A compiled regular expression pattern for variable substitution.

    Methods
    -------
    upload_file(local_path: str):
        Uploads a file to the object storage container.
    object_exists(local_path: str) -> bool:
        Checks if an object exists in the object storage container.
    """

    VARIABLE_PATTERN = re.compile(r'\$\{([^}]+)}')
    COMPRESSION_EXTENSIONS = {
        'gzip': 'gz',
        'bzip2': 'bz2',
        'lzma': 'xz',
        'brotli': 'br'
    }

    def __init__(self, config):
        """
        Constructs all the necessary attributes for the LibcloudObjectStorage object.

        Parameters
        ----------
        config : Config
            Configuration object containing settings for job logs and storage.

        Raises
        ------
        ValueError
            If the storage provider or container name is not defined in the configuration.
        """
        self._storage_provider = config.joblogs().get('storage_provider')
        if self._storage_provider is None:
            logger.error("Storage provider is not defined in the configuration.")
            raise ValueError("Storage provider is not defined")

        self._container_name = config.joblogs().get('container_name')
        if self._container_name is None:
            logger.error("Container name is not set in the configuration.")
            raise ValueError("Container name is not set")

        # Reading the compression method from the config and setting default to 'gzip'
        self.compression_method = config.joblogs().get('compression_method', None)

        args_envs = config.joblogs_storage(self._storage_provider)
        args = {}
        for arg, value in args_envs.items():
            value_str = str(value)
            substituted_value = self._substitute_variables(value_str, arg)
            logger.debug(f"Substituted value for '{arg}': {substituted_value}")
            args[arg] = substituted_value

        driver_class = get_driver(self._storage_provider)
        try:
            self.driver = driver_class(**args)
            logger.info(f"Initialized driver for storage provider '{self._storage_provider}'.")
        except Exception as e:
            logger.exception(f"Failed to initialize driver for storage provider '{self._storage_provider}': {e}")
            raise

    def _substitute_variables(self, value, arg_name):
        """
        Replaces placeholders in the configuration value with environment variable values.

        Parameters
        ----------
        value : str
            The configuration value possibly containing placeholders.
        arg_name : str
            The name of the argument being processed (for logging purposes).

        Returns
        -------
        str
            The value with placeholders replaced by environment variable values.

        Raises
        ------
        ValueError
            If the required environment variable is not set.
        """
        def replace_var(match):
            env_var = match.group(1)
            env_value = os.getenv(env_var)
            if env_value is not None:
                env_value = env_value.strip().strip('"').strip("'")
                return env_value
            else:
                logger.error(f"Environment variable '{env_var}' is not set for argument '{arg_name}'.")
                raise ValueError(f"Environment variable '{env_var}' is not set for argument '{arg_name}'.")

        result = self.VARIABLE_PATTERN.sub(replace_var, value)
        result = result.replace(r'\${', '${')
        return result

    def upload_file(self, project, spider, local_path):
        """
        Uploads a file to the object storage container.

        Parameters
        ----------
        local_path : str
            The job_id that is passed as a local path.
        project : str
            The name of the project.
        spider : str
            The name of the spider.

        Returns
        -------
        None

        Logs
        ----
        Logs information about the upload status or errors encountered.
        """
        job_id = os.path.basename(local_path).replace('.txt', '')
        compressed_file_path = None
        file_to_upload = local_path
        object_name = None

        try:
            if self.compression_method:
                try:
                    compression = Compression(self.compression_method)
                    compressed_file_path = compression.compress(local_path)
                    file_to_upload = compressed_file_path
                    extension = self.COMPRESSION_EXTENSIONS.get(self.compression_method, self.compression_method)
                    object_name = f"logs/{project}/{spider}/{job_id}.log.{extension}"
                except Exception as e:
                    logger.error(f"Compression failed, will upload uncompressed file: {e}")
                    # Fallback to uncompressed upload
                    object_name = f"logs/{project}/{spider}/{job_id}.log"
            else:
                # No compression
                object_name = f"logs/{project}/{spider}/{job_id}.log"
                logging.debug(f"Uploading uncompressed file '{object_name}'.")

            container = self.driver.get_container(container_name=self._container_name)
            with open(file_to_upload, 'rb') as file:
                self.driver.upload_object_via_stream(
                    file,
                    container,
                    object_name,
                    extra=None,
                    headers=None
                )

            logger.info(f"Successfully uploaded compressed file '{object_name}' to container '{self._container_name}'.")
        except (ObjectError, ContainerDoesNotExistError, InvalidContainerNameError) as e:
            logger.exception(f"Error uploading the file '{object_name}': {e}")
        except Exception as e:
            logger.exception(f"An unexpected error occurred while uploading '{object_name}': {e}")
        finally:
            # Remove temporary file even if upload fails
            if compressed_file_path and os.path.exists(compressed_file_path):
                os.remove(compressed_file_path)
                logger.debug(f"Removed temporary compressed file '{compressed_file_path}'.")

    def object_exists(self, prefix):
        """
        Checks if any object exists in the container that starts with the given prefix.

        Parameters
        ----------
        prefix : str
            The prefix to match object names against.

        Returns
        -------
        bool
            True if at least one object with the given prefix exists, False otherwise.

        Logs
        ----
        Logs information about the existence check or errors encountered.
        """
        container = self.driver.get_container(container_name=self._container_name)
        try:
            objects = self.driver.list_container_objects(container=container, prefix=prefix)
            if objects:
                logger.debug(f"At least one object with prefix '{prefix}' exists in container '{self._container_name}'.")
                return True
            else:
                logger.debug(f"No objects with prefix '{prefix}' found in container '{self._container_name}'.")
        except ContainerDoesNotExistError:
            logger.error(f"Container '{self._container_name}' does not exist in the cloud storage.")
        except InvalidContainerNameError:
            logger.error(f"Invalid container name '{self._container_name}'.")
        except Exception as e:
            logger.exception(f"An unexpected error occurred while listing objects with prefix '{prefix}': {e}")
        return False
