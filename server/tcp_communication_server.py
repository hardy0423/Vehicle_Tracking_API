import socketserver
import threading
import logging
import queue
import socket
import time
from django.db.models import Q
from devices.models import Device, Trajectory
from utils.crc16_algo import CRC16
import crcmod
from .record_data_processing import extract_records, send_records_to_api, extract_records_extended
from django.db import connection
from concurrent.futures import ThreadPoolExecutor

# Constants
CODEC_AVL_1 = 0x08  # Codec 8
CODEC_AVL_2 = 0x0C
CODEC_AVL_3 = 0x8E  # Codec 8 extended

HOST = "0.0.0.0"
PORT = 5023
SOCKET_TIMEOUT = 30  # Timeout pour les opérations socket
COMMAND_TIMEOUT = 15  # Timeout pour l'envoi de commandes
MAX_THREADS = 50 # Nombre maximum de connexions simultanées
IDLE_SLEEP = 1.0

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Queue to store failed API requests for retrying later
data_queue = queue.Queue()

# Global dictionary to store active device connections
devices = {}
devices_lock = threading.Lock()



class ThreadPoolTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """
    Custom TCP server with a limited thread pool to prevent system overload.
    """
    def __init__(self, *args, **kwargs):
        # Create a fixed-size thread pool instead of unbounded threads
        self.executor = ThreadPoolExecutor(max_workers=MAX_THREADS)
        super().__init__(*args, **kwargs)
    
    def process_request(self, request, client_address):
        """Submit client request handling to the thread pool instead of spawning unlimited threads."""
        self.executor.submit(self.process_request_thread, request, client_address)
    
    def process_request_thread(self, request, client_address):
        """Executed by the thread pool to process each client request."""
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)
    
    def server_close(self):
        """Perform a clean shutdown of the server and gracefully stop all worker threads."""
        super().server_close()
        self.executor.shutdown(wait=True, cancel_futures=True)


class TCPServerConsumer:
    """
    Manages the TCP server lifecycle (start, stop, status).
    Ensures safe startup, shutdown, and thread handling.
    """
    
    def __init__(self):
        self.server = None
        self.is_running = False  # Prevents multiple server instances from starting
        self._shutdown_event = threading.Event()  # Used for graceful manual shutdown

    def start_server(self):
        """Initialize and start the TCP server."""
        try:
            # Create and configure the thread-pooled TCP server
            self.server = ThreadPoolTCPServer(
                (HOST, PORT), 
                TCPConnectionHandler,
                bind_and_activate=False
            )
            
            # Configure server behavior and socket properties
            self.server.allow_reuse_address = True
            self.server.daemon_threads = True
            self.server.server_bind()
            self.server.server_activate()
            
            self.is_running = True
            self._shutdown_event.clear()
            
            # Run server loop with poll_interval to prevent busy CPU loops
            try:
                self.server.serve_forever(poll_interval=1.0)
            except Exception as e:
                logger.error(f"Server serve_forever error: {e}", exc_info=True)
            
        except OSError as e:
            if e.errno == 98:
                logger.error(f"Port {PORT} is already in use. Cannot start server.")
            else:
                logger.error(f"OS error starting TCP server: {e}")
                
        except Exception as e:
            logger.error(f"Error in TCP server: {e}", exc_info=True)
            
        finally:
            # Always ensure proper cleanup on shutdown
            self.is_running = False
            if self.server:
                try:
                    self.server.server_close()
                    logger.info("TCP Server closed")
                except Exception as e:
                    logger.error(f"Error closing server: {e}")

    def stop_server(self):
        """Gracefully stop the TCP server and close all active device connections."""
        if not self.is_running:
            logger.info("TCP server is not running")
            return

        logger.info("Stopping TCP server...")
        
        self._shutdown_event.set()
        
        # Close all active device connections safely
        with devices_lock:
            for imei, sock in list(devices.items()):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                try:
                    sock.close()
                    logger.info(f"[{imei}] Socket closed")
                except Exception as e:
                    logger.debug(f"[{imei}] Error closing socket: {e}")
            devices.clear()

        # Stop the main server loop
        if self.server:
            try:
                self.server.shutdown()
                logger.info("TCP server shutdown signal sent")
            except Exception as e:
                logger.error(f"Error during server shutdown: {e}")

        logger.info("TCP server stopped successfully")

    def get_active_devices(self):
        """Return a list of currently connected device IMEIs."""
        with devices_lock:
            return list(devices.keys())

    def is_device_connected(self, imei):
        """Check if a device (IMEI) is currently connected to the server."""
        with devices_lock:
            return imei in devices


class TCPConnectionHandler(socketserver.BaseRequestHandler):
    """
    Handles an individual TCP client connection.
    Responsible for:
      - IMEI validation
      - Receiving and parsing AVL data
      - Sending ACK responses
      - Managing connection lifecycle
    """

    devices = devices  # Reference to global device connections dictionary
    devices_lock = devices_lock  # Lock for thread-safe device management

    def setup(self):
        """Configure socket options and timeout before handling client."""
        super().setup()
        self.request.settimeout(SOCKET_TIMEOUT)
        self.request.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

    def handle(self):
        """
        Main handler loop for managing client communication.
        Optimized to reduce CPU usage and handle reconnections safely.
        """
        ip, port = self.client_address
        logger.info(f"Connection established with {ip}:{port}")
        imei = None
        consecutive_timeouts = 0
        max_consecutive_timeouts = 3
        
        try:
            # Step 1: Receive and validate IMEI
            imei = self.receive_and_validate_imei()
            if not imei:
                logger.warning(f"[{ip}:{port}] Invalid or missing IMEI. Closing connection.")
                return

            # Step 2: Register device connection (replace old one if it exists)
            with self.devices_lock:
                if imei in devices:
                    try:
                        old_sock = devices[imei]
                        old_sock.close()
                        logger.info(f"[{imei}] Closed previous connection")
                    except:
                        pass
                devices[imei] = self.request

            logger.info(f"[{imei}] Device registered successfully from {ip}:{port}")

            # Step 3: Continuously receive AVL data packets
            while True:
                try:
                    avl_data = self.receive_and_validate_avl_data()
                    
                    if avl_data is None:
                        # No data received: sleep to reduce CPU load
                        time.sleep(IDLE_SLEEP)
                        consecutive_timeouts += 1
                        
                        # Disconnect if too many idle timeouts
                        if consecutive_timeouts >= max_consecutive_timeouts:
                            logger.warning(f"[{imei}] Too many consecutive timeouts, closing connection")
                            break
                        continue
                    
                    # Reset timeout counter when data is received
                    consecutive_timeouts = 0
                    
                    if avl_data:
                        self.process_and_send_avl_data_to_api(avl_data, imei)
                    else:
                        logger.warning(f"[{imei}] Invalid AVL data received")
                        time.sleep(IDLE_SLEEP)
                        
                except socket.timeout:
                    # Handle timeout — used to detect inactivity
                    time.sleep(IDLE_SLEEP)
                    consecutive_timeouts += 1
                    
                    if consecutive_timeouts >= max_consecutive_timeouts:
                        logger.info(f"[{imei}] Connection idle, closing")
                        break
                    continue
                    
                except (ConnectionResetError, BrokenPipeError) as e:
                    logger.info(f"[{imei}] Client disconnected: {e}")
                    break
                    
                except Exception as e:
                    logger.error(f"[{imei}] Error processing AVL data: {e}", exc_info=True)
                    break

        except (ConnectionResetError, BrokenPipeError) as e:
            logger.info(f"[{ip}:{port}] Client disconnected during IMEI: {e}")
            
        except socket.timeout:
            logger.warning(f"[{ip}:{port}] Connection timeout during IMEI reception")
            
        except Exception as e:
            logger.error(f"[{ip}:{port}] Error during connection handling: {e}", exc_info=True)
            
        finally:
            # Cleanup after disconnection
            logger.info(f"[{imei or 'Unknown'}] Disconnecting from {ip}:{port}")
            if imei:
                with self.devices_lock:
                    devices.pop(imei, None)
                    logger.info(f"[{imei}] Removed from active devices")
            
            # Close socket connection gracefully
            try:
                self.request.shutdown(socket.SHUT_RDWR)
            except:
                pass
            
            try:
                self.request.close()
            except Exception as e:
                logger.debug(f"Error closing socket: {e}")
            
            # Clean up database connections
            try:
                connection.close_if_unusable_or_obsolete()
                logger.debug(f"[{imei or 'Unknown'}] Database connection cleaned")
            except Exception as e:
                logger.debug(f"Error closing DB connection: {e}")


    def receive_data(self, length):
        """
        Receive exact amount of data with timeout handling.
        
        Args:
            length (int): Number of bytes to receive
            
        Returns:
            bytes: Received data or None if timeout/error
        """
        data = b''
        
        while len(data) < length:
            try:
                remaining = length - len(data)
                packet = self.request.recv(min(remaining, 4096))
                
                if not packet:
                    logger.debug(f"Connection closed while receiving data")
                    return None
                    
                data += packet
                
            except socket.timeout:
                if len(data) > 0:
                    logger.warning(f"Timeout while receiving data. Got {len(data)}/{length} bytes")
                return None
                
            except Exception as e:
                logger.error(f"Error receiving data: {e}")
                return None
                
        return data

    def send_response(self, response: bytes) -> bool:
        """
        Sends a response to the device and logs the action.
        
        Args:
            response (bytes): Response to send
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.request.sendall(response)
            logger.debug(f"Sent response: {response.hex()}")
            return True
            
        except socket.timeout:
            logger.error(f"Timeout while sending response")
            return False
            
        except Exception as e:
            logger.error(f"Failed to send response: {e}")
            return False

    def receive_and_validate_imei(self):
        """
        Receives and validates the IMEI from the device.

        Returns:
            str: The validated IMEI, or None if invalid.
        """
        ip, port = self.client_address
        
        try:
            # Recevoir la longueur de l'IMEI (2 bytes)
            imei_length_data = self.receive_data(2)
            if not imei_length_data:
                logger.warning(f"[{ip}:{port}] No IMEI length received")
                self.send_response(b'\x00')
                return None

            imei_length = int.from_bytes(imei_length_data, byteorder="big")
            
            if imei_length != 15:
                logger.warning(f"[{ip}:{port}] Invalid IMEI length: {imei_length}")
                self.send_response(b'\x00')
                return None

            # Recevoir l'IMEI
            imei_data = self.receive_data(imei_length)
            if not imei_data:
                logger.warning(f"[{ip}:{port}] Incomplete IMEI received")
                self.send_response(b'\x00')
                return None

            imei = imei_data.decode(errors="ignore")
            logger.info(f"[{ip}:{port}] Received IMEI: {imei}")

            # Vérifier si l'appareil existe et est actif
            if not Device.objects.filter(Q(imei=imei) & Q(is_actif=True)).exists():
                logger.warning(f"[{ip}:{port}] Unknown or inactive IMEI: {imei}")
                self.send_response(b'\x00')
                return None

            # Envoyer ACK
            if not self.send_response(b'\x01'):
                logger.warning(f"[{ip}:{port}] Failed to send IMEI acceptance for: {imei}")
                return None

            logger.info(f"[{imei}] IMEI validated successfully")
            return imei

        except socket.timeout:
            logger.warning(f"[{ip}:{port}] Timeout while receiving IMEI")
            return None
            
        except Exception as e:
            logger.error(f"[{ip}:{port}] Error receiving IMEI: {e}", exc_info=True)
            try:
                self.send_response(b'\x00')
            except:
                pass
            return None

    def receive_and_validate_avl_data(self):
        """
        Receives and validates the AVL data.
        See https://wiki.teltonika-gps.com/view/Help_with_Server_FAQ

        Returns:
            bytes: The AVL data, or None if timeout, or empty bytes if invalid.
        """
        try:
            # Recevoir le préambule (4 bytes)
            preamble = self.receive_data(4)
            if not preamble:
                return None
                
            if preamble != b'\x00\x00\x00\x00':
                logger.warning(f"Invalid preamble: {preamble.hex()}")
                return b''

            # Recevoir la longueur des données (4 bytes)
            data_length_data = self.receive_data(4)
            if not data_length_data:
                return None
                
            avl_length = int.from_bytes(data_length_data, byteorder="big")
            
            if avl_length <= 0 or avl_length > 10000:  # Limite de sécurité
                logger.warning(f"Invalid AVL length: {avl_length}")
                self.send_response(b'\x00\x00\x00\x00')
                return b''

            # Recevoir les données AVL
            avl_data = self.receive_data(avl_length)
            if not avl_data or len(avl_data) != avl_length:
                logger.warning(f"Incomplete AVL data. Expected {avl_length}, got {len(avl_data) if avl_data else 0}")
                return b''

            # Recevoir le CRC (4 bytes: 2 padding + 2 CRC)
            crc_full = self.receive_data(4)
            if not crc_full:
                logger.warning("Failed to receive CRC")
                return b''

            # Vérifier le CRC
            crc16_func = crcmod.predefined.mkCrcFun('crc-16')
            crc_calculated = crc16_func(avl_data)
            crc_received = int.from_bytes(crc_full[2:], byteorder='big')
            
            if crc_calculated != crc_received:
                logger.warning(f"CRC mismatch! Calculated: {hex(crc_calculated)}, Received: {hex(crc_received)}")
                self.send_response(b'\x00\x00\x00\x00')
                return b''

            logger.debug(f"AVL data received and validated: {len(avl_data)} bytes")
            return avl_data

        except socket.timeout:
            # Timeout normal - pas de données disponibles
            return None
            
        except Exception as e:
            logger.error(f"Error receiving AVL data: {e}", exc_info=True)
            return b''

    def process_and_send_avl_data_to_api(self, avl_data, imei):
        """
        Validates, processes, and sends AVL data to the API.

        Args:
            avl_data (bytes): The AVL data to process.
            imei (str): The IMEI of the device.
        """
        try:
            if len(avl_data) < 2:
                logger.warning(f"[{imei}] AVL data too short: {len(avl_data)} bytes")
                self.send_response(b'\x00\x00\x00\x00')
                return

            codec_id = avl_data[0]
            num_records = avl_data[1]
            
            logger.info(f"[{imei}] Processing CODEC ID: {hex(codec_id)}, Records: {num_records}")

            records = None
            
            if codec_id == CODEC_AVL_1:  # Codec 8 standard
                records = extract_records(avl_data, imei, num_records)
                
            elif codec_id == CODEC_AVL_3:  # Codec 8 Extended
                records = extract_records_extended(avl_data, imei, num_records)
                
            else:
                logger.warning(f"[{imei}] Unsupported CODEC ID: {hex(codec_id)}")
                self.send_response(b'\x00\x00\x00\x00')
                return

            # Envoyer l'ACK avec le nombre de records traités
            ack_response = num_records.to_bytes(4, byteorder="big")
            if not self.send_response(ack_response):
                logger.error(f"[{imei}] Failed to send ACK for {num_records} records")
                return

            # Envoyer les records à l'API
            if records:
                print("RECORDS: ", records)
                logger.info(f"[{imei}] Sending {len(records)} records to API")
                send_records_to_api(records, codec_id)
            else:
                logger.warning(f"[{imei}] No valid records extracted from AVL data")

        except Exception as e:
            logger.error(f"[{imei}] Error during AVL processing: {e}", exc_info=True)
            try:
                self.send_response(b'\x00\x00\x00\x00')
            except:
                pass

    @classmethod
    def send_command_to_device(cls, imei, command, timeout=COMMAND_TIMEOUT):
        """
        Send a command to the device using the active connection.
        See https://wiki.teltonika-gps.com/view/FMC130_SMS/GPRS_Commands
        
        Args:
            imei (str): Device IMEI
            command (str or bytes): Command to send
            timeout (int): Timeout in seconds
            
        Returns:
            str or False: Response from device or False if failed
        """
        with cls.devices_lock:
            if imei not in devices:
                logger.warning(f"[{imei}] Device not connected")
                return False

            device_socket = devices[imei]
            
            # Vérifier si le socket est valide
            try:
                if device_socket.fileno() == -1:
                    logger.warning(f"[{imei}] Socket is closed. Removing from active devices")
                    del devices[imei]
                    return False
            except Exception as e:
                logger.warning(f"[{imei}] Invalid socket: {e}")
                del devices[imei]
                return False

        # Préparer la commande
        try:
            if isinstance(command, str):
                command_bytes = bytes.fromhex(command)
            else:
                command_bytes = command

            # Sauvegarder le timeout original
            original_timeout = device_socket.gettimeout()
            
            try:
                device_socket.settimeout(timeout)
                
                # Envoyer la commande
                device_socket.sendall(command_bytes)
                logger.info(f"[{imei}] Command sent: {command_bytes.hex()}")

                # Recevoir la réponse
                response = device_socket.recv(1024)
                
                if not response:
                    logger.warning(f"[{imei}] No response received from device")
                    return False

                response_ascii = response.decode("ascii", errors="ignore")
                logger.info(f"[{imei}] Response received (ASCII): {response_ascii}")
                return response_ascii

            finally:
                # Restaurer le timeout original
                device_socket.settimeout(original_timeout)

        except socket.timeout:
            logger.error(f"[{imei}] Timeout while sending command")
            return False
            
        except Exception as e:
            logger.error(f"[{imei}] Failed to send command: {e}", exc_info=True)
            return False
