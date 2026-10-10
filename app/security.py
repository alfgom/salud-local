"""Local-only network policy. No DNS, proxies, redirects or external sockets."""
import sys
import socket

OLLAMA_PORT = 11435

def network_guard(event, args):
    if event == 'socket.sendto':
        raise PermissionError('UDP saliente bloqueado')
    if event == 'socket.connect':
        address = args[1]
        if not isinstance(address, tuple) or address[0] != '127.0.0.1' or address[1] != OLLAMA_PORT:
            raise PermissionError('Conexión saliente bloqueada por Salud Local')
    if event == 'socket.getaddrinfo':
        if args[0] != '127.0.0.1':
            raise PermissionError('Resolución DNS bloqueada')
    if event == 'socket.bind':
        address = args[1]
        if isinstance(address, tuple) and address[0] != '127.0.0.1':
            raise PermissionError('Solo se permite escuchar en 127.0.0.1')

def install():
    sys.addaudithook(network_guard)
