
class CRC16:
    def __init__(self):
        self.poly = 0xA001  # Polynôme CRC-16/IBM (inversé)
        self.init = 0xFFFF  # Valeur initiale
        self.xor_out = 0x0000  # XOR final

    def crc16_ibm(self, data: bytes) -> int:
        """Calcule le CRC-16/IBM pour une séquence de données."""
        crc = self.init  # Initialisation du CRC
        byte_number = 0  # Indicateur de l'octet en cours

        while byte_number < len(data):
            current_byte = data[byte_number]
            crc ^= current_byte  # XOR avec l'octet courant
            bit_number = 0  # Indicateur du bit en cours

            while bit_number < 8:  # Boucle sur chaque bit de l'octet
                carry = crc & 0x0001  # Calcul du carry
                crc >>= 1  # Décalage du CRC
                if carry:  # Si Carry == 1
                    crc ^= self.poly  # Appliquer le XOR avec le polynôme
                bit_number += 1  # Incrémenter le bit number

            byte_number += 1  # Incrémenter le byte number

        return crc & 0xFFFF  # Retourner le CRC sur 16 bits
    
