import base64, hashlib, os, hmac
def _tripcode(data,salt):
    code = ''
    for digest in ['sha512','sha256']:
        h = hashlib.new(digest)
        h.update(data)
        h.update(code)
        h.update(salt)
        code = h.digest()
        del h
    h = hmac.new(salt)
    h.update(code)
    code = h.digest()
    return base64.b32encode(code).replace('=','')

def socks_connect(host,port,socks_host):
    s = socket.socket()
    s.connect(socks_host)
    # socks connect
    s.send(struct.pack('BB',4,1))
    s.send(struct.pack('!H',port))
    s.send(struct.pack('BBBB',0,0,0,1))
    s.send('proxy\x00')
    s.send(host)
    s.send('\x00')
    # socks recv response
    d = s.recv(8)
    if len(d) != 8 or d[0] != '\x00':
        return None, 'Invalid Response From Socks Proxy'
    if d[1] == '\x5a':
        return s , 'Connection Okay'
    elif d[1] == '\x5b':
        return None, 'Connection Rejected / Failed'
    else:
        return None, 'Socks Error got response code %s'%[d[1]]


_salt = 'salt'
if os.path.exists('salt'):
    with open('salt') as s:
       _salt = s.read()

tripcode = lambda nick, trip : _tripcode(nick+'|'+trip,_salt)
i2p_connect = lambda host: socks_connect(host,0,('127.0.0.1',9911))
tor_connect = lambda host,port: socks_connect(host,port,('127.0.0.1',9050))
