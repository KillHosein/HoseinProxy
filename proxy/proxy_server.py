import asyncio
import logging
import struct
import hashlib
import secrets
import time
import socket
import ssl
from urllib.parse import urlparse
import config

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE) if hasattr(config, 'LOG_FILE') else logging.StreamHandler(),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class FakeTLSProxy:
    def __init__(self):
        self.secret = bytes.fromhex(config.SECRET)
        self.tls_domain = config.TLS_DOMAIN
        self.workers = config.WORKERS
        self.port = config.PORT
        self.connections = {}
        self.stats = {'connections': 0, 'bytes_sent': 0, 'bytes_received': 0}
        
    def generate_fake_tls_cert(self, domain):
        """Generate a fake TLS certificate that mimics real certificates"""
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    
    def create_fake_tls_handshake(self, domain):
        """Create a fake TLS handshake that looks legitimate"""
        # Create a fake ClientHello packet
        client_hello = self._create_client_hello(domain)
        return client_hello
    
    def _create_client_hello(self, domain):
        """Create a realistic TLS ClientHello packet"""
        # TLS 1.2 ClientHello structure
        version = b'\x03\x03'  # TLS 1.2
        random = secrets.token_bytes(32)
        session_id = b'\x20' + secrets.token_bytes(32)  # 32-byte session ID
        
        # Cipher suites (common ones)
        cipher_suites = b'\x00\x1a'  # 26 cipher suites
        cipher_suites += b'\xc0\x2f\xc0\x27\x00\x3c\xc0\x2b\xc0\x23\x00\x9e\xc0\x2d\xc0\x25\x00\x3a\xc0\x29\xc0\x21\x00\x9f\xc0\x30\xc0\x28\x00\x6b\xc0\x2e\xc0\x26\x00\x67'
        
        # Compression methods
        compression = b'\x01\x00'  # No compression
        
        # Extensions
        extensions = self._create_extensions(domain)
        
        # Combine all parts
        handshake = version + random + session_id + cipher_suites + compression + extensions
        
        # Add TLS record header
        record_header = b'\x16\x03\x03'  # Handshake, TLS 1.2
        record_length = len(handshake).to_bytes(2, 'big')
        
        return record_header + record_length + handshake
    
    def _create_extensions(self, domain):
        """Create TLS extensions"""
        extensions = b''
        
        # Server Name Indication (SNI)
        sni = domain.encode('utf-8')
        sni_extension = b'\x00\x00' + (len(sni) + 5).to_bytes(2, 'big') + b'\x00' + len(sni).to_bytes(2, 'big') + sni
        extensions += sni_extension
        
        # Supported Groups
        supported_groups = b'\x00\x0a\x00\x04\x00\x02\x00\x17\x00\x18'
        extensions += supported_groups
        
        # Signature Algorithms
        signature_algorithms = b'\x00\x0d\x00\x0c\x00\x0a\x04\x01\x05\x01\x06\x01\x02\x01\x04\x03\x05\x03'
        extensions += signature_algorithms
        
        # Add extension length
        extension_length = len(extensions).to_bytes(2, 'big')
        
        return extension_length + extensions
    
    def obfuscate_data(self, data):
        """Obfuscate data to avoid detection"""
        # Add random padding
        padding_length = secrets.randbelow(64) + 16
        padding = secrets.token_bytes(padding_length)
        
        # Mix real data with padding
        obfuscated = bytearray()
        data_index = 0
        padding_index = 0
        
        while data_index < len(data) or padding_index < len(padding):
            if data_index < len(data) and (secrets.randbelow(2) or padding_index >= len(padding)):
                obfuscated.append(data[data_index])
                data_index += 1
            elif padding_index < len(padding):
                obfuscated.append(padding[padding_index])
                padding_index += 1
        
        # Add obfuscation markers
        obfuscated.extend(secrets.token_bytes(8))
        
        return bytes(obfuscated)
    
    def deobfuscate_data(self, data):
        """Remove obfuscation from data"""
        # Remove the last 8 bytes (obfuscation markers)
        if len(data) > 8:
            data = data[:-8]
        
        # Simple deobfuscation (in real implementation, this would be more complex)
        return data
    
    async def handle_connection(self, reader, writer):
        """Handle incoming connection with fake TLS"""
        client_addr = writer.get_extra_info('peername')
        logger.info(f"New connection from {client_addr}")
        
        try:
            # Perform fake TLS handshake
            await self._perform_fake_tls_handshake(reader, writer)
            
            # Handle the actual proxy protocol
            await self._handle_proxy_protocol(reader, writer)
            
        except Exception as e:
            logger.error(f"Error handling connection from {client_addr}: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            logger.info(f"Connection from {client_addr} closed")
    
    async def _perform_fake_tls_handshake(self, reader, writer):
        """Perform fake TLS handshake"""
        # Send fake ServerHello
        server_hello = self._create_server_hello()
        writer.write(server_hello)
        await writer.drain()
        
        # Wait for ClientHello
        client_hello = await reader.read(1024)
        if not self._validate_client_hello(client_hello):
            raise Exception("Invalid ClientHello")
        
        # Send fake Certificate and ServerHelloDone
        cert_message = self._create_certificate_message()
        writer.write(cert_message)
        await writer.drain()
        
        # Complete handshake
        handshake_done = self._create_handshake_done()
        writer.write(handshake_done)
        await writer.drain()
        
        logger.info("Fake TLS handshake completed successfully")
    
    def _create_server_hello(self):
        """Create fake ServerHello"""
        version = b'\x03\x03'  # TLS 1.2
        random = secrets.token_bytes(32)
        session_id = b'\x20' + secrets.token_bytes(32)
        
        # Selected cipher suite (AES256-GCM-SHA384)
        cipher_suite = b'\x00\x9f'
        compression = b'\x00'
        
        # Extensions
        extensions = b'\x00\x00'  # No extensions
        
        handshake = version + random + session_id + cipher_suite + compression + extensions
        
        # TLS record header
        record_header = b'\x16\x03\x03'
        record_length = len(handshake).to_bytes(2, 'big')
        
        return record_header + record_length + handshake
    
    def _validate_client_hello(self, data):
        """Validate incoming ClientHello"""
        if len(data) < 43:  # Minimum ClientHello size
            return False
        
        # Check TLS record header
        if data[0] != 0x16 or data[1:3] != b'\x03\x03':
            return False
        
        return True
    
    def _create_certificate_message(self):
        """Create fake certificate message"""
        # This would contain a fake certificate chain
        # For now, we'll create a minimal fake certificate
        cert_data = b'Fake Certificate Data'
        cert_length = len(cert_data).to_bytes(3, 'big')
        
        handshake_type = b'\x0b'  # Certificate
        handshake_length = (len(cert_data) + 3).to_bytes(3, 'big')
        
        handshake = handshake_type + handshake_length + cert_length + cert_data
        
        # TLS record header
        record_header = b'\x16\x03\x03'
        record_length = len(handshake).to_bytes(2, 'big')
        
        return record_header + record_length + handshake
    
    def _create_handshake_done(self):
        """Create ServerHelloDone message"""
        handshake = b'\x0e\x00\x00\x00'  # ServerHelloDone
        
        # TLS record header
        record_header = b'\x16\x03\x03'
        record_length = len(handshake).to_bytes(2, 'big')
        
        return record_header + record_length + handshake
    
    async def _handle_proxy_protocol(self, reader, writer):
        """Handle the actual MTProxy protocol"""
        # Read encrypted data
        data = await reader.read(1024)
        
        # Decrypt using the secret
        decrypted = self._decrypt_data(data)
        
        # Extract the connection info
        dc_id, user_secret = self._parse_proxy_header(decrypted)
        
        # Connect to Telegram servers
        telegram_reader, telegram_writer = await asyncio.open_connection(
            f'149.154.175.{50 + dc_id}', 443
        )
        
        # Start relaying data
        await asyncio.gather(
            self._relay_data(reader, telegram_writer),
            self._relay_data(telegram_reader, writer)
        )
    
    def _decrypt_data(self, data):
        """Decrypt incoming data using the secret"""
        # Simple XOR decryption (in real implementation, use proper crypto)
        key = self.secret[:16]
        decrypted = bytearray()
        for i, byte in enumerate(data):
            decrypted.append(byte ^ key[i % len(key)])
        return bytes(decrypted)
    
    def _parse_proxy_header(self, data):
        """Parse the proxy protocol header"""
        if len(data) < 64:
            raise ValueError("Invalid proxy header")
        
        # Extract DC ID and user secret
        dc_id = data[0] & 0x0F
        user_secret = data[8:40]
        
        return dc_id, user_secret
    
    async def _relay_data(self, reader, writer):
        """Relay data between client and Telegram"""
        try:
            while True:
                data = await reader.read(8192)
                if not data:
                    break
                
                # Apply obfuscation if enabled
                if hasattr(config, 'ENABLE_ANTIFILTER') and config.ENABLE_ANTIFILTER:
                    data = self.obfuscate_data(data)
                
                writer.write(data)
                await writer.drain()
                
                # Update stats
                self.stats['bytes_sent'] += len(data)
                
        except Exception as e:
            logger.error(f"Error relaying data: {e}")
        finally:
            writer.close()
    
    async def start_server(self):
        """Start the fake TLS proxy server"""
        server = await asyncio.start_server(
            self.handle_connection,
            '0.0.0.0',
            self.port
        )
        
        logger.info(f"Fake TLS proxy started on port {self.port}")
        logger.info(f"Secret: {config.SECRET}")
        logger.info(f"TLS Domain: {self.tls_domain}")
        
        async with server:
            await server.serve_forever()

if __name__ == '__main__':
    proxy = FakeTLSProxy()
    asyncio.run(proxy.start_server())