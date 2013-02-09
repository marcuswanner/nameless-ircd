from services import Service
import asynchat, asyncore, json, socket, struct, sqlite3, threading, time, os, base64


def is_onion(addr):
    if len(addr) != 16:
        return False
    for c in addr:
        if c not in '234567abcdefghijklmnopqrstuvwxyz':
            return False
    return True
    

class TC_Connection(asynchat.async_chat):
    def __init__(self,sock,parent,peer_onion=None):
        asynchat.async_chat.__init__(self,sock)
        self.set_terminator('\n')
        self.peer_onion = peer_onion
        self.our_onion = parent.onion
        self.parent = parent
        self.dbg = lambda m : self.parent.dbg('TC_Connection: %s'%m)
        self.ibuffer = ''
        self.peer_status = 'handshake'
        self.our_status = 'handshake'
        self.nick = property(lambda : '%s.onion'%self.peer_onion)
        self.usr = property(lambda : self.name)
        self.name = 'torchat'
        self.ready = lambda : 'handshake' not in [self.peer_status,self.our_status]
        self.chans = []
        self.sendq = []
        self.server = parent.server
        self.last_ping = property(lambda: int(time.now()))
        self.last_active = 0
        self.cookie = property(lambda : self.parent.get_cookie(self.peer_onion),
                               lambda c: self.parent.put_cookie(self.peer_onion,c))


    def event(self,src,type,msg):
        self.send_msg('[%s] %s: %s'%(src,type,msg))

    def status(self):
        yield 'our_onion=%s' % self.our_onion
        yield 'peer_onion=%s' % self.peer_onion
        yield 'our_status=%s' % self.our_status
        yield 'peer_status=%s' % self.peer_status
        yield 'nick=%s' % self.nick
        yield 'user=%s' % self.usr
        yield 'user_mask=%s' % self
        yield 'ready=%s' % self.ready()
        

    def handle_error(self):
        self.parent.handle_error()
        self.parent.fork_reconnect(self.our_onion)

    def kill(self,reason):
        self.send_msg('[Killing] %s'%reason)
        self.close_when_done()

    def join_chan(self,chan):
        if chan in self.chans:
            return
        self.server.join_channel(self,chan)
        self.send_msg('[%s] Joined'%chan)

    def collect_incoming_data(self,data):
        self.ibuffer += data

    def nick_change(self,user,newnick):
        self.send_msg('[Nick Change] %s -> %s'%(user.nick,newnick))

    def privmsg(self,src,msg):
        if src == self.server.admin:
            self.send_msg(msg)
            return
        elif src[0] in ['#','&']:
            self.send_msg('[%s] %s'%(src,msg))

    def send_notice(self,src,msg):
        self.send_msg('[Notice from %s]: %s'%(src,msg))

    def send_ping(self):
        if self.ready():
            self.send_status()

    def on_ping(self,ping):
        pass

    def got_not_implemented(self,data):
        pass

    def complete_handshake(self):
        self.send_proto('ping',self.cookie)
        while not self.ready():
            time.sleep(5)
            self.dbg('ourstatus=%s peerstatus=%s'%(self.our_status,self.peer_status))
        self.dbg('Completing Handshake')
        self.send_status()
        self.parent.got_new_user(self)
        self.dbg('Handshake Completed')
        
    def on_pong(self):
        pass

    def timeout(self):
        self.handle_close()

    def handle_close(self):
        for chan in self.chans:
            self.part_chan(chan)
        self.parent.close_peer(self)


    def got_status(self,status):
        self.dbg('%s oldstatus=%s status=%s'%(self.peer_onion,self.peer_status,status))
        self.peer_status = status
        self.last_active = time.now()

    def encode_text(self,data):
        return data.encode('UTF-8')

    def decode_text(self,data):
        return data.decode('UTF-8').encode('ascii',errors='replace').replace('?','x')
    
    def decode_msg(self,data):
        return data.replace('\r\n', '\n').replace('\r', '\n').replace('\x0b', '\n').replace('\n', os.linesep)

    def got_profile_name(self,name):
        self.name = self.decode_text(name)

    def got_message(self,data):
        self.parant.got_message(self,self.decode_msg(data))

    def got_profile_text(self,text):
        pass

    def got_avatar_data(self,data):
        pass

    def got_add_me(self,data):
        pass

    def got_remove_me(self,data):
        pass

    def got_client(self, data):
        self.dbg('%s client=%s'%(self.peer_onion,data))
    
    def got_version(self, data):
        self.dbg('%s version=%s'%(self.peer_onion,data))

    def got_pong(self, data):
        if self.parent.check_cookie(self.peer_onion,data):
            self.dbg('bad cookie from %s :%s'%(self.peer_onion,data))
            self.parent.close_peer(self)

    def send_info(self):
        self.send_proto_text('version','nameless-ircd')
        self.send_proto_text('profile_name',self.server.name)
        self.send_proto_text('profile_text','nameless ircd')
        

    def ping_ok(self,onion):
        self.send_proto_text('pong',self.cookie)
        self.send_info()
        self.our_status = 'available'

    def got_ping(self, ping):
        onion, cookie = self.split_text(ping)
        self.dbg('Ping: Onion=%s cookie=%s'%(onion,[cookie]))
        if not is_onion(onion):
            self.dbg('%s is not an onion'%onion)
        elif self.parent.has_onion(onion):
            if not self.parent.is_online(onion) and self.parent.check_cookie(onion,cookie):
                self.ping_ok(onion)
                return
            else:
                self.dbg('already online or bad cookie from %s : cookie=%s'%(onion,cookie))
        else:
            self.peer_onion = onion
            self.cookie = cookie
            self.ping_ok(onion)
            return
        self.parent.close_peer(self)


    def split_text(self,text):
        sp = text.split(' ')
        try:
            a = sp[0]
            b = ' '.join(sp[1:])
        except:
            a = text
            b = ''
        return a, b


    def send_raw(self,data):
        self.send_msg('[RAW] %s'%data)

    def send_msg(self,msg):
        if not self.ready():
            self.sendq.append(msg)
            return
        while len(self.sendq) > 0:
            self.send_proto('message', self.sendq.pop(0))
        self.send_proto('message',msg)

    def send_proto_text(self,proto,text):
        self.send_proto(proto,self.encode_text(text))

    def send_proto(self,proto,data):
        self.push('%s %s\n'%(proto,self.encode(data)))

    def send_status(self):
        self.send_proto('status',self.our_status)

    def on_proto(self,proto,data):
        self.dbg('Protocol=%s data=%s'%(proto,[data]))
        data = self.decode(data)
        proto = 'got_%s'%proto.lower()
        if hasattr(self,proto):
            getattr(self,proto)(data)
        else:
            self.send_proto('not_implemented',proto)

    def encode(self,msg):
        return msg.replace('\\', '\\/').replace('\n', '\\n')
    
    def decode(self,msg):
        return msg.replace('\\n', '\n').replace('\\/', '\\')

    def user_mask(self):
        return '%s.onion!%s.torchat@%s'%(self.peer_onion,self.name,self.server.name)

    def __str__(self):
        return self.user_mask()
    
    def found_terminator(self):
        inbuff = self.ibuffer
        self.ibuffer = ''
        proto, blob = self.split_text(inbuff)
        self.on_proto(proto,blob)

class TC_Listener(asyncore.dispatcher):
    
    def __init__(self,parent):
        asyncore.dispatcher.__init__(self)
        self.create_socket(socket.AF_INET,socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind(parent.bind_addr)
        self.listen(5)
        self.parent = parent
        self.dbg = lambda m : parent.server.dbg('TC_Listener: %s'%m)

    def handle_accept(self):
        p = self.accept()
        if p is not None:
            sock, addr = p
            self.dbg('Incomming Connection %s'%[addr])
            self.parent.got_connection(sock)

class tcserv(Service):
    def __init__(self,server,cfg_fname='tcserv.json'):
        Service.__init__(self,server)
        self.nick = 'tcserv'
        self.cfg_fname = cfg_fname
        self.handle_error = server.handle_error
        self.dbg = lambda m : self.server.dbg('TCServ: %s'%m)
        self._db_lock = threading.Lock()
        self._lock_db = self._db_lock.acquire
        self._unlock_db = self._db_lock.release
        self.onion_peers = {}
        self.db_name = ':memory:'
        self.peers = 0
        self.unlisted_peers = []
        self._load_config()
        self.listener = TC_Listener(self)
        self.connect_all()

    def is_online(self,onion):
        return onion in self.onion_peers

    def check_cookie(self,onion,cookie):
        return self.get_cookie(onion) == cookie
    
    def get_cookie(self,onion):
        def exe(c):
            c.execute('SELECT COUNT(cookie) FROM peers WHERE onion=?',(onion,))
            if c.fetchone()[0] == 0:
                cookie = base64.b64encode(os.random(128))
                self.dbg('new cookie for %s : %s'%(onion,cookie))
                return cookie
            c.execute('SELECT cookie FROM peers WHERE onion=?',(onion))
            return c.fetchone()[0]
        return self.db_exec(exe)

    def has_onion(self,onion):
        def exe(c):
            c.execute('SELECT COUNT(onion) FROM peers WHERE onion=?',(onion,))
            return c.fetchone()[0] > 0
        self.db_exec(exe)

    def put_cookie(self,onion,cookie):
        def exe(c):
            c.execute('INSERT INTO peers ( onion , cookie ) VALUES ( ? , ? )',(onion,cookie))
        self.db_exec(exe,commit=True)

    def close_peer(self,con):
        if con.peer_onion in self.onion_peers:
            con = self.onion_peers.pop(con.peer_onion)
        con.close()

    def _fork(self,func):
        def f():
            try:
                func()
            except:
                self.handle_error()
        threading.Thread(target=f,args=()).start()
        
    def _load_config(self):
        with open(self.cfg_fname) as r:
            j = json.load(r)
        self.tc_port = 11009
        self.onion = j['tc_onion']
        if 'tc_db' in j:
            self.db_name = j['tc_db']
        self.reconnect_timeout = 1
        if 'tc_reconnect' in j:
            self.reconnect_timeout = j['tc_reconnect']
        self.onion_peers = {}
        self.bind_addr = ('127.0.0.1',self.tc_port)
        self._init_db()

    def _init_db(self):
        lines = ['CREATE TABLE IF NOT EXISTS peers ( onion VARCHAR(16) , cookie TEXT , UNIQUE( onion ) )']
        def init(c):
            for line in lines:
                c.execute(line)
        if self.db_name != ':memory:' and not os.path.exists(self.db_name):
            with open(self.db_name,'w') as w:
                w.write('')
        self.db_exec(init,commit=True)

    def connect_all(self):
        self.peers = 0
        for onion in self._load_peers():
            self._fork(lambda : _connect(onion))
            self.peers += 1

    def db_exec(self,func,commit=False):
        self._lock_db()
        ret = None
        try:
            con = sqlite3.connect(self.db_name)
            c = con.cursor()
            ret = func(c)
            if commit:
                con.commit()
            c.close()
            con.close()
        finally:
            self._unlock_db()
    
        return ret

    def _load_peers(self):
        def exe(c):
            ret = []
            for onion in c.execute('SELECT onion FROM peers'):
                ret.append(onion)
            return ret
        return self.db_exec(exe)

    def onion_fail(self,onion,msg):
        self.dbg('Onion %s failed: %s'%(onion,msg)) 

    def _connect(self,onion):
        self.dbg('Connecting to %s'%onion)
        con = self.blocking_connect_onion(onion)
        if con is None:
            self.dbg('Failed to connect to %s reconnect in %d seconds'%(onion,self.reconnect_timeout))
            time.sleep(self.reconnect_timeout)
            self.fork_reconnect(onion)
            return
        self.dbg('waiting for %s handshake'%onion)
        con.complete_handshake()
        self.onion_peers[onion] = con
        self.dbg('handshake from %s completed'%onion)

    def got_new_user(self,con):
        self.dbg('new user %s'%con)
        self.server.add_user(con)
        self.unlisted_peers.remove(con)

    def fork_reconnect(self,onion):
        if onion in self.onion_peers:
            peer = self.onion_peers.pop(onion)
            del peer
        self._fork(lambda : self._connect(onion))



    def got_message(self,con,msg):
        if msg[0] == ':':
            parts = msg.split(' ')
            self.got_cmd(con,parts[0][1:],parts[1:])
            return
        if self.admin is None:
            self.con.send_msg('[AutoReply] Offline')
            return
        self.server.admin.privmsg(con,msg)

    def got_broadcast(self,con,dest,msg):
        if dest[0] not in ['#','&']:
            self.dbg('Got Invaild Broadcast destination from %s: %s'%(con.peer_onion,dest))
            return
        if dest not in con.chans:
            self.server.join_channel(con,dest)
        self.server.chans[dest].privmsg(con,dest)

    def got_cmd(self,con,cmd,args):
        if cmd == 'join':
            for chan in args:
                if chan[0] in ['#', '&']:
                    con.join_chan(chan)
                else:
                    con.send_msg('[%s] invalid channel name'%(chan))

        elif cmd in ['pm','m','msg']:
            self.server.privmsg(con,args[0],' '.join(args[1:]))
        elif cmd[0] in ['#','&']:
            self.server.privmsg(con,cmd,args)

    def got_connection(self,sock):
        self.unlisted_peers.append(TC_Connection(sock,self))

    def blocking_connect_onion(self,onion):
        self.dbg('Blocking Connect to %s:%d'%(onion,self.tc_port))
        s, e = tor_connect(onion,self.tc_port)
        if s is None:
            self.onion_fail(onion,e)
            return None
        return TC_Connection(s,self,peer_onion=onion)

    def serve(self,user,msg):
        if user != self.server.admin:
            self.server.kill(user,'service abuse')
            return
        msg = msg.strip()
        if msg == 'reboot':
            self.reboot(user)
        elif msg == 'status':
            self.send_status(user)


    def kill_all(self):
        for o, c in self.onion_peers:
            self.close_peer(c)
        while len(self.unlisted_peers) > 0:
            self.close_peer(self.unlisted_peers.pop(0))

    def server_status(self):
        return 'Unlisted %d/%d Connected %d/%d'%(
            len(self.unlisted_peers),self.peers,
            len(self.onion_peers.items()),self.peers)

    def reboot(self,user):
        user.privmsg(self,'killing all')
        def work():
            self.kill_all()
            while len(self.onion_peers.items()) > 0 and len(self.unlisted_peers) > 0:
                time.sleep(1)
                user.privmsg(self,self.server_status())
            user.privmsg(self,'connecting all')
            self.connect_all()
        self._fork(work)

    def send_status(self,user): 
        user.privmsg(self,self.server_status())
        user.privmsg(self,'====')
        user.privmsg(self,'Unlisted')
        user.privmsg(self,'====')
        for u in self.unlisted_peers:
            user.privmsg(self,'Unlisted peer: %s'%u)
            for m in u.status():
                user.privmsg(self,'-- %s'%m)
        user.privmsg(self,'====')
        user.privmsg(self,'Connected')
        user.privmsg(self,'====')
        for onion , u in self.onion_peers:
            user.privmsg(self,'Connected Peer: %s'%u)
            for m in u.status():
                user.privmsg(self,'-- %s'%m)
        user.privmsg(self,'====')

raise Exception('DO NOT USE tcserv it is not ready yet')
