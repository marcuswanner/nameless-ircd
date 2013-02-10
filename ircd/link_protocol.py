import struct, hmac

delim = '\r\n.\r\n' 

def sign(data):
    # this doesn't actually do anything useful yet
    return data + '\x01' + hmac.new('nameless',data).hexdigest()


def pack(data,proto_version=1):
    """
    pack data + sig for sending on s2s connection
    """
    # int 1:
    # protocol version
    # int 2:
    # length of data message
    head = struct.pack('II',proto_version,len(data))
    return head + sign(data) + delim

def unpack(data,proto_version=1):
    """
    unpack data + sig for s2s
    """
    version,dlen = struct.unpack('II',data[8:])
    if version != proto_version:
        raise Exception('got incompatable version: '+str(version))
    data = data[8:8+dlen]
    sig = data[8-dlen:]
    return data, sig

def verify(data):
    # this doesn't actually do anything useful yet
    p = data.split('\x01')
    if len(p) == 2 and hmac.new('nameless',p[0]).hexdigest() == p[1]:
        return p[0],p[1]
    return None, None
