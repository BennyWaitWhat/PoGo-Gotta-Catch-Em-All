import socket
try:
    s = socket.create_connection(("1.1.1.1", 443), 5)
    print("NET_OK (raw network reachable without DNS)")
    s.close()
except Exception as e:
    print("NET_FAIL", repr(e))
try:
    print("DNS_OK", socket.gethostbyname("github.com"))
except Exception as e:
    print("DNS_FAIL", repr(e))
