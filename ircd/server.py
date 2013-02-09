from asynchat import async_chat
from asyncore import dispatcher
from time import time as now
from time import sleep
from random import randint as rand
from threading import Thread
import user
import socket,asyncore,base64,os,threading,traceback
import services

BaseUser = user.BaseUser

class Channel:
    def __init__(self,name,server):
        self.users = []
        self.server =  server
        self.topic = None
        self.name = name
        self.is_anon = lambda : self.name.startswith('&')
        self.empty = lambda : len(self.users) == 0
        self.is_invisible = self.name[1] == '.'
        
    def set_topic(self,user,topic):
        if user not in self.users:
            user.send_num(442, "%s :You're not on that channel"%self.name)
            return
        self.topic = topic
        self.send_topic()

    def nick_change(self,user,newnick):
        if self.is_anon():
            return
        for u in self.users:
            if u == user:
                continue
            u.nick_change(user,newnick)

    def send_raw(self,msg):
        for user in self.users:
            user.send_raw(msg)

    def __str__(self):
        return self.name

    def __len__(self):
        return len(self.users)

    def send_topic(self):
        for user in self.users:
            self.send_topic_to_user(user)

    def send_topic_to_user(self,user):
        if self.is_invisible and user not in self.users:
            return
        if self.topic is None:
            user.send_num(331,'%s :No topic is set'%self.name)
            return
        user.send_num(332 ,'%s :%s'%(self.name,self.topic))

    def joined(self,user):
        if user in self.users:
            return
        self.users.append(user)
        for u in self.users:
            if self.is_anon():
                if u == user:
                    u.event(user.user_mask(),'join',self.name)
                if self.is_invisible:
                    continue
                u.send_notice(self,'%s -- %s online'%(self.name,len(self.users)))
            else:
                u.event(user.user_mask(),'join',self.name)
        self.send_topic_to_user(user)
        self.send_who(user)

    def user_quit(self,user,reason='quitting'):
        if user not in self.users:
            return
        self.users.remove(user)
        user.event(user,'part',self.name)
        for u in self.users:
            if not self.is_anon():
                u.event(user,'part',self.name)
            else:
                u.send_notice(self.name,'%s -- %s online'%(self.name,len(self.users)))  
        if self.empty():
            self.server.remove_channel(self.name)

    def privmsg(self,orig,msg):
        for user in self.users:
            if user == orig:
                continue
            src = 'anonymous!anon@%s'%self.server.name
            if not self.is_anon():
                src = '%s!anon@%s'%(orig.nick,self.server.name)
                if user == orig:
                    src = orig.user_mask()
            user.send_raw(':%s PRIVMSG %s :%s'%(src,self.name,msg))

    def send_who(self,user):
        mod = '='  or ( self.is_invisible and '@' ) or (self.name[0] == '&' and '*' )
        if self.is_anon():
            user.send_num(353,'%s %s :%s anonymous'%(mod,self.name,user.nick))
        else:
            nicks = ''
            for u in self.users:
                nicks += ' ' + u.nick    
            user.send_num(353,'%s %s :%s'%(mod, self.name,nicks.strip()))
        user.send_num(366,'%s :End of NAMES list'%self.name)


class _user(async_chat):
    def __init__(self,sock):
        async_chat.__init__(self,sock)
        self.set_terminator('\r\n')
        self.buffer = ''

    def collect_incoming_data(self,data):
        self.buffer += data
        if len(self.buffer) > 1024:
            self.close()
    
    def found_terminator(self):
        b = self.buffer
        self.buffer = ''
        self.got_line(b)

    def send_msg(self,msg):
        self.push(msg+'\r\n')



class User(_user,BaseUser):
    
    def __init__(self,sock,server):
        BaseUser.__init__(self,server)
        _user.__init__(self,sock)
    
    def handle_close(self):
        self.close_user()
        self.close()

class Server(dispatcher):
    def __init__(self,addr,name='nameless',do_log=False):
        self._no_log = not do_log
        dispatcher.__init__(self)
        self.create_socket(socket.AF_INET,socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind(addr)
        self.listen(5)
        self.admin_backlog = []
        self.admin = None
        self.name = name
        self.chans = dict()
        self.users = dict()
        self.pingtimeout = 60 * 5
        self.ping_retry = 2
        self.threads = []
        self.handlers = []
        self.on =True
        for t in [self.pingloop,self.pongloop,self.adminloop]:
            t = self._fork(t)
            self.threads.append(t)
        self.service = dict()
        for t in self.threads:
            t.start()
        for k in services.services.keys():
            self.service[k] = services.services[k](self)
            self.add_user(self.service[k])


    def toggle_debug(self):
        self._no_log = not self._no_log

    def debug(self):
        return not self._no_log

    def _fork(self,func):
        def f():
            try:
                func()
            except:
                self.err(traceback.format_exc())
        return threading.Thread(target=f,args=())
    def motd(self):
        d = ''
        with open('motd','r') as f:
            d += f.read()
        return d

    def kill(self,user,reason):
        user.kill(user)
        self.close_user(user)

    def privmsg(self,user,dest,msg):
        msg = msg[1:]
        onion = user.nick.endswith('.onion')
        self.dbg('privmsg %s -> %s -- %s'%(user.nick,dest,msg))
        if (dest[0] in ['&','#'] and not self._has_channel(dest)) or (dest[0] not in ['&','#'] and not self.has_nick(str(user))):
            user.send_num(401,'%s :No such nick/channel'%dest)
            return
        if dest.endswith('serv'):
            dest = dest.lower().split('serv')[0]
            if not self.has_service(dest):
                user.privmsg(dest,'no such service')
                return
            self.service[dest].serve(self,user,msg)
            return 
        if dest[0] in ['#','&']:
            dest =  dest.lower()
            if dest in user.chans:
                self.chans[dest].privmsg(user,msg)
        else:
            if dest in self.users:
                self.users[dest].privmsg(user,msg)
            
    def set_admin(self,user):
        if self.admin is not None:
            self.admin.privmsg(self.service['admin'],'no longer oper')
        self.admin = user
        def new_close():
            User.handle_close(self.admin)
            self.admin = None
        self.admin.handle_close = new_close
        self.admin.privmsg(self.service['admin'],'you are now oper ;3')

    def send_global(self,msg):
        for user in self.users.values():
            user.send_notice('globalserv!service@nameless',msg)

    def has_service(self,serv):
        return serv.lower() in self.service.keys()


    def has_nick(self,nick):
        return nick.split('!')[0] in self.users.keys()
    

    def _log(self,type,msg):
        if self._no_log:
            return
        with open('log/server.log','a') as f:
            f.write('[%s -- %s] %s\n'%(type,now(),msg))


    def send_motd(self,user):
        user.send_num(375,':- %s Message of the day -'%self.name)
        for line in self.motd().split('\n'):
            user.send_num(372, ':- %s '%line)
        user.send_num(376, ':- End of MOTD command')

    def send_welcome(self,user):
        if not user.nick.endswith('.onion'):
            user.send_num('001','HOLY CRAP CONNECTED')
            #user.send_num('002','Your host is %s, running version nameless-ircd'%self.name)
            #user.send_num('003','This server was created a while ago')
            #user.send_num('004','%s nameless-ircd x m'%self.name)
        self.send_motd(user)
        if hasattr(user,'after_motd') and user.after_motd is not None:
            user.after_motd()
        if user.nick.endswith('.onion'):
            return
        user.welcomed = True

    def dbg(self,msg):
        self._log('DBG',msg)


    def _iter(self,f_iter,f_cycle,timesleep):
        while self.on:
            f_cycle()
            for nick,user in self.users.items():
                try:
                    f_iter(user)
                except:
                    self.handle_error()
            sleep(timesleep)
    

    def err(self,msg):
        try:
            with open('log/errors.log','a') as a:
                a.write(msg)
                a.write('\n')
        except:
            pass


    def handle_error(self):
        self.err(traceback.format_exc())

    def close_user(self,user):
        if user.nick.endswith('serv'):
            return
        try:
            user.close_user()
            del user
        except:
            self.err(traceback.format_exc())

    def pongloop(self):
        def check_ping(user):
            if now() - user.last_ping_recv > self.pingtimeout:
                self.dbg('ping timeout %s'%user)
                user.timeout()
        def nop():
            pass
        self._iter(check_ping,nop,self.pingtimeout)

    
    def send_admin(self,msg):
        for line in str(msg).split('\n'):
            if self.admin is None:
                self.admin_backlog.append(msg)
            else:
                while len(self.admin_backlog) > 0:
                    self.admin.privmsg('adminserv!service@%s'%self.name,self.admin_backlog.pop(0))
                self.admin.privmsg('adminserv!service@%s'%self.name,line)
            with open('log/admin.log','a') as a:
                a.write('%s -- %s'%(now(),msg))
                a.write('\n')
    def adminloop(self):
        # wont work on windows
        if not hasattr(socket,'AF_UNIX'):
            return
        adminsock = socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        sock = 'admin.sock'
        if os.path.exists(sock):
            os.unlink(sock)
        adminsock.bind(sock)

        while self.on:
            try:
                data = adminsock.recv(1024)
                for line in data.split('\n'):
                    self.service['admin'].handle_line(line)
            except:
                self.send_admin(traceback.format_exc())
        adminsock.close()

    def pingloop(self):
        def ping(user):
            self.dbg('ping %s'%user)
            user.send_ping()
                
        def debug():
            self.dbg('sending pings')
        self._iter(ping,debug,self.pingtimeout/self.ping_retry)
            

    def _has_channel(self,chan):
        return chan in self.chans.keys()

    def add_user(self,user):
        self.dbg('Adding User: %s'%user.nick)
        if user.nick in self.users:
            self.err('user %s already in users'%user)
            return
        self.users[user.nick] = user
        if user.nick.endswith('serv'):
            return
        self.send_welcome(user)


    def has_user(self,nick):
        return nick in self.users.keys()

    def send_list(self,user):
        user.send_num(321,'Channel :Users  Name')
        for chan in self.chans:
            chan = self.chans[chan]
            if chan.is_invisible():
                continue
            user.send_num(322,'%s %d :%s'%(chan.name,len(chan),chan.topic or ''))
        user.send_num(323 ,':End of LIST')

    def _add_channel(self,chan):
        chan = chan.lower()
        self.dbg('New Channel %s'%chan)
        self.chans[chan] = Channel(chan,self)

    def join_channel(self,user,chan):
        if chan in user.chans:
            return
        chan = chan.lower()
        if chan[0] in ['&','#']:
            if not self._has_channel(chan):
                self._add_channel(chan)
                user.send_notice('chanserv!service@%s'%self.name,'new channel %s'%chan)
            self.chans[chan].joined(user)
            user.chans.append(chan)
        else:
            user.send_notice('chanserv!service@%s'%self.name,'bad channel name: %s'%chan)

    def remove_channel(self,chan):
        chan = chan.lower()
        if self._has_channel(chan):
            self.chans.pop(chan)
                
    def part_channel(self,user,chan):
        chan = chan.lower()
        if chan in self.chans:
            self.chans[chan].user_quit(user)

    def change_nick(self,user,newnick):
        self.dbg('server nick change %s -> %s' % (user.nick,newnick))
        if user.nick in self.users:
            self.users[user.nick].send_num(433, "%s :Nickname is already in use"%user.nick)
            return
        self.users[user.nick] = user
        self.users[newnick] = self.users.pop(user.nick)
        user.nick_change(user,newnick)
        for chan in user.chans:
            self.dbg('inform %s of nick change'%chan)
            if chan in self.chans:
                self.chans[chan].nick_change(user,newnick)
        user.nick = newnick
        user.usr = newnick
        self.dbg('user is now %s'%user)

    def stop(self):
        pass

    def handle_accept(self):
        pair = self.accept()
        if pair is not None:
            sock, addr = pair
            User(sock,self)
