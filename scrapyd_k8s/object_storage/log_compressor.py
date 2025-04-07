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
        self._compression_handlers = {
            'gzip': self._handle_streaming_compression(gzip.open),
            'bzip2': self._handle_streaming_compression(bz2.BZ2File),
            'lzma': self._handle_streaming_compression(lzma.open),
            'brotli': self._handle_brotli_compression
        }

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
                # Get the appropriate compression handler and call it
                handler = self._compression_handlers[self.method]
                result = handler(input_file_path, temp_compressed_file)

                logger.info(
                    f"Successfully compressed file to '{temp_compressed_file}' using {self.method} compression.")
                return result
            except Exception as e:
                logger.error(f"Error during compression: {e}")
                raise

    def _handle_streaming_compression(self, open_func):
        """
        Create a handler for streaming compression methods (gzip, bzip2, lzma).

        Parameters
        ----------
        open_func : callable
            The function to open a compressed file (e.g., gzip.open).

        Returns
        -------
        callable
            A function that handles the compression.
        """

        def handler(input_file_path, output_file_path):
            with open(input_file_path, 'rb') as f_in:
                with open_func(output_file_path, 'wb') as f_out:
                    while chunk := f_in.read(self.COMPRESSION_CHUNK_SIZE):
                        f_out.write(chunk)
            return output_file_path

        return handler

    def _handle_brotli_compression(self, input_file_path, output_file_path):
        """Handle the brotli compression method."""
        with open(input_file_path, 'rb') as f_in:
            compressed_data = brotli.compress(f_in.read())
        with open(output_file_path, 'wb') as f_out:
            f_out.write(compressed_data)
        return output_file_path

