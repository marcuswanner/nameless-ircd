from services import Service, admin
from user import User
from util import socks_connect
from asynchat import async_chat
from asyncore import dispatcher
import json,socket,os,base64,threading

class listener(dispatcher):
    
    def __init__(self,parent):
        dispatcher.__init__(self)
        self.parent = parent
        self.create_socket(socket.AF_INET,socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind(self.parent.bind_addr)
        self.listen(5)
        self.dbg = lambda m : self.parent.dbg('linkserv Listener>> %s'%m)

    def handle_accept(self):
        p = self.accept()
        if p is not None:
            sock,addr = p
            self.dbg('got connection from %s'%[addr])
            link_recv(sock,self.parent)

class link(async_chat):
    

    def __init__(self,sock,parent,name='?'):
        async_chat.__init__(self,sock)
        self.parent = parent
        self.server = parent.server
        self.set_terminator(self.parent.delim)
        self.ibuffer = ''
        self.state = 0
        self.name = name
        self.dbg = lambda m : self.parent.dbg('link-%s %s'%(self.name,m))
        self.handle_error = self.server.handle_error
        self.init()

    def send_msg(self,data):
        self.push(json.dumps(data)+self.parent.delim)
        
    def collect_incoming_data(self,data):
        self.ibuffer += data

    def found_terminator(self):
        data = self.ibuffer
        self.ibuffer = ''
        try:
            j = json.loads(data)
        except:
            self.bad_fomat()
            return
        if 'error' in j:
            self.dbg('ERROR: %s'%j['error'])
            return
        self.on_message(data)


    def error(self,msg):
        self.dbg('error: %s'%msg)
        self.send_msg({'error':msg})
        self.close_when_done()

    def bad_format(self):
        self.error('bad format')

    def on_message(self,data):
        pass

    def init(self):
        pass

    def parse_message(self,data):
        for e in ['data','event','dst']:
            if e not in data:
                self.bad_format()
                return
        self.got_message(data['event'],data['data'],data['dst'])
            
    def got_message(self,event,data,dst):
        event = event.lower()
        if not hasattr(self,'_got_%s'%event):
            self.error('bad event')
            return
        try:
            getattr(self,'_got_%s'%event)(dst,data)
        except:
            self.handle_error()

    def _got_raw(self,dst,data):
        if dst[0] in ['&', '#'] :
            if dst in self.server.chans:
                dst = self.server.chans[dst]
            else:
                return
        else:
            if dst in self.server.users:
                dst = self.server.users[dst]
            else:
                return
        dst.send_raw(data)        


class link_user(User):

    def __init__(self,link,nick):
        self.link = link
        User.__init__(self,link.server)
        self.nick = nick
        self.usr = nick
    
    def send_msg(self,msg):
        self.link.send_msg({'data':msg,'event':'raw','dst':str(self)})

class link_send(link):

    def init(self):
        self.send_msg({'server':self.server.name,'login':self.parent.get_login(self.dest)})
        self.state += 1

    def on_message(self,data):
      
        if self.state == 1:
            if 'auth' not in data:
                self.error('bad auth')
                return
            if data['auth'].lower() == 'ok':
                self.state += 1
        elif self.state == 2:
            if 'sync' not in data:
                self.error('bad sync')
                return
            if data['sync'] == 'done':
                self.state += 1
                return
            else:
                if 'chans' in data['sync']:
                    for chan in data['sync']['chans']:
                        for attr in ['topic','name']:
                            if attr not in chan:
                                self.error('channel format')
                                return
                        if chan['name'][0] not in ['&','#']:
                            self.error('channel format')
                            return
                        if chan['name'] not in self.server.chans:
                            self.server.chans[chan['name']] = Chan(chan['name'],self.server)
                            self.server.chans[chan['name']].topic = chan['topic']
                if 'users' in data['sync']:
                    for user in data['sync']['users']:
                        for attr in ['nick','chans']:
                            if attr not in user:
                                self.error('user format')
                                return
                        if user['nick'] not in self.server.users:
                            user = link_user(self,user['nick'])
                            self.server.users[user.nick] = user
                        for chan in user['chans']:
                            self.server.join_channel(self.server.users[user['nick']],chan)

        elif self.state == 3:
            self.parse_message(data)


class link_recv(link):

    def on_message(self,data):
        if self.state == 0:
            for e in ['server','login']:
                if e not in data:
                    self.bad_format()
                    return
            if self.parent.check(data['server'],data['login']):
                self.name = data['server']
                self.parent.links.append(self)
                self.servver.send_admin('server linked: %s'%self.name)
                self.send_msg({'auth':'ok'})
                # should be chunked
                self.send_msg({
                        'sync':{
                            'chans':self.server.chans.keys(),
                            'users':self.server.users.keys()
                            }
                        })
                self.send_msg({'sync':'done'})
                self.state += 1
            else:
                self.error('bad auth')
        if self.state == 1:
            self.parse_message(data)
            
class linkserv(Service):
    _yes =  ['y','yes','1','true']
    def __init__(self,server,cfg_fname='linkserv.json'):
        Service.__init__(self,server)
        self.nick = 'linkserv'
        self.delim = '\r\n.\r\n'
        self.links = []
        self._cfg_fname = cfg_fname
        self._lock = threading.Lock()
        self._unlock = self._lock.release
        self._lock = self._lock.acquire
        j = self.get_cfg()
        if 'autoconnect' in j and j['autoconnect'] in self._yes:
            self.connect_all()
        
    @admin
    def serve(self,server,user,msg):
        msg = msg.strip()
        p = msg.split(' ')
        if msg == 'list':
            self.list_links(user)
        elif msg == 'reload':
            user.privmsg(self,'reloading...')
            try:
                self.reload()
            except:
                user.privmsg(self,'error reloading')
                for line in traceback.format_exc().split('\n'):
                    user.privmsg(self,line)
            else:
                user.privmsg(self,'reloaded')
        elif msg == 'kill':
            user.privmsg(self,'killing all links')
            try:
                self.kill_links()
                self.wait_for_links_dead()
            except:
                user.privmsg(self,'error')
                for line in traceback.format_exc().split('\n'):
                    user.privmsg(self,line)
            else:
                user.privmsg(self,'killed')

    def list_links(self,user):
        if len(self.links) == 0:
            user.privmsg(self,'NO LINKS')
        for link in self.links:
            user.privmsg(self,'LINK: %s'%link.name)
                
    def kill_links(self):
        pass

    def wait_for_links_dead(self):
        pass

    def reload(self):
        pass

    def _fork(self,f):
        def func():
            try:
                f()
            except:
                for line in traceback.format_exc():
                    self.server.send_admin('link error: %s'%line)
        threading.Thread(target=func,args=()).start()


    def connect_all(self):
        j = self.get_cfg()

        def connect(link,login):
            if not link.startswith('127.'):
                host,port = tup(j['tor'].split(':'))
                if link.endswith('.i2p'):
                    host,port = tup(j['i2p'].split(':'))
                port = int(port)
                sock, err = socks_connect(login,9999,(host,port))
            else:
                sock = socket.socket()
                sock.connect(link,9999)
                err = None
            if err is not None:
                self.server.send_admin('link error: %s %s'%(link,err))
            else:
                self.server.send_admin('start link: %s'%link)
                link_send(sock,self,link)

        for link, login in j['links'].items():
            self._fork(lambda: connect(link,login))


    def get_cfg(self):
        self._lock()
        with open(self._cfg_fname) as r:
            j = json.load(r)
        self._unlock()
        return j

    def set_cfg(self,cfg):
        self._lock()
        with open(self._cfg_fname,'w') as w:
            json.dump(cfg,w)
        self._unlock()
        

    def check(self,server,login):
        j = self.get_cfg()
        if dest not in j['links']:
            if 'allow_all' not in j:
                return False
            elif str(j['allow_all']).lower() in self._yes :
                j['links'][dest] = login
                self.set_cfg(j)
                return self.check(dest,data)
            else:
                return False
        return data == j['links'][dest]


