import struct
import crcmod

def create_codec12_command(ascii_command):
    """
    Creates a Codec12 command frame based on the given ASCII command.

    Arguments:
    - ascii_command: The command to be sent to the device, in ASCII format.

    Returns:
    - str: The full Codec12 command frame in hexadecimal format.

    See https://wiki.teltonika-gps.com/view/Codec#Codec_12
    """
    # Constants for Codec12 frame structure
    PREAMBLE = b'\x00\x00\x00\x00'  # 4-byte preamble
    CODEC_ID = b'\x0C'              # Codec ID (1 byte)
    COMMAND_QUANTITY_1 = b'\x01'    # Command quantity 1 (1 byte)
    COMMAND_TYPE = b'\x05'          # Command type (0x05 for command)
    COMMAND_QUANTITY_2 = b'\x01'    # Command quantity 2 (1 byte)

    # Convert ASCII command to hexadecimal
    command_hex = ascii_command.encode('ascii')

    # Calculate data size (from Codec ID to Command Quantity 2)
    data_size = len(CODEC_ID + COMMAND_QUANTITY_1 + COMMAND_TYPE + struct.pack('>I', len(command_hex)) + command_hex + COMMAND_QUANTITY_2)
    data_size_bytes = struct.pack('>I', data_size)  # Data size in 4 bytes (big-endian)

    # Calculate command size in 4 bytes (big-endian)
    command_size_bytes = struct.pack('>I', len(command_hex))

    # Build the frame without CRC-16
    frame_without_crc = (
        PREAMBLE +
        data_size_bytes +
        CODEC_ID +
        COMMAND_QUANTITY_1 +
        COMMAND_TYPE +
        command_size_bytes +
        command_hex +
        COMMAND_QUANTITY_2
    )

    # Calculate CRC-16 using CRC-16/IBM
    crc16_func = crcmod.predefined.mkCrcFun('crc-16')
    crc16 = crc16_func(frame_without_crc[8:])  # Calculate from Codec ID onward
    crc16_bytes = struct.pack('>I', crc16)    # Convert CRC to 4 bytes (big-endian)

    # Add the CRC-16 to the frame
    full_frame = frame_without_crc + crc16_bytes

    # Return the frame in hexadecimal format
    return full_frame.hex().upper()
