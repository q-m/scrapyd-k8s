import gzip
import bz2
import lzma
import tempfile
import logging

logger = logging.getLogger(__name__)

try:
    import brotli
    BROTLI_AVAILABLE = True
except ImportError:
    BROTLI_AVAILABLE = False
    logger.warning("Brotli module not available. Brotli compression will not be supported.")

class Compression:
    """
    A class to handle compression of logs in different formats (gzip, bz2, lzma, brotli) using disk-based files.
    """

    SUPPORTED_METHODS = ['gzip', 'bzip2', 'lzma', 'brotli']
    COMPRESSION_CHUNK_SIZE = 1024

    def __init__(self, method="gzip"):
        """
        Initializes the compression method.

        Parameters
        ----------
        method : str
            The compression method to use. Default is 'gzip'.

        Raises
        ------
        ValueError
            If the compression method is not supported.
        """
        if method not in self.SUPPORTED_METHODS:
            raise ValueError(
                f"Unsupported compression method: {method}. Supported methods are {', '.join(self.SUPPORTED_METHODS)}")
        self.method = method

    def compress(self, input_file_path):
        """
        Compresses the given input file and saves the compressed file on disk.

        Parameters
        ----------
        input_file_path : str
            The path to the file to compress.

        Returns
        -------
        str
            Path to the compressed file.
        """
        # Create a temporary file for the compressed data
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.log.{self.method}') as temp_file:
            temp_compressed_file = temp_file.name

            try:
                if self.method == "gzip":
                    with open(input_file_path, 'rb') as f_in:
                        with gzip.open(temp_compressed_file, 'wb') as f_out:
                            while chunk := f_in.read(self.COMPRESSION_CHUNK_SIZE):
                                f_out.write(chunk)
                elif self.method == "bzip2":
                    with open(input_file_path, 'rb') as f_in:
                        with bz2.BZ2File(temp_compressed_file, 'wb') as f_out:
                            while chunk := f_in.read(self.COMPRESSION_CHUNK_SIZE):
                                f_out.write(chunk)
                elif self.method == "lzma":
                    with open(input_file_path, 'rb') as f_in:
                        with lzma.open(temp_compressed_file, 'wb') as f_out:
                            while chunk := f_in.read(self.COMPRESSION_CHUNK_SIZE):
                                f_out.write(chunk)
                elif self.method == "brotli":
                    with open(input_file_path, 'rb') as f_in:
                        compressed_data = brotli.compress(f_in.read())
                    with open(temp_compressed_file, 'wb') as f_out:
                        f_out.write(compressed_data)

                logger.info(
                    f"Successfully compressed file to '{temp_compressed_file}' using {self.method} compression.")
                return temp_compressed_file

            except Exception as e:
                logger.error(f"Error during compression: {e}")
                raise

        return temp_compressed_file

