from time import time as now
import util
import base64, os
class User:
    def __init__(self,server):
        self.after_motd = None
        self.last_ping_recv = now()
        self.server = server
        self.host = 'nameless'
        self.nick = ''
        self.usr = ''
        self.name = ''
        self.last_ping = 0
        self.chans = []
        self.welcomed = False
        self._bad_chars = [
            '!','@','#','$','%',
            '^','&','*','(',')',
            '=','+','/','?','"',
            "'",'~','.',',',
            ]
        self.__str__ = self.user_mask
        self.dbg = lambda msg: server.dbg('%s : %s'%(self,msg))
        self.handle_error = self.server.handle_error


    def send_notice(self,src,msg):
        self.action(src,'notice',msg)

    def privmsg(self,src,msg):
        self.action(src,'privmsg',msg)

    def action(self,src,type,msg):
        self.send_raw(':%s %s %s :%s'%(src, type.upper(),self.user_mask(),msg))

    def close_user(self):
        self.dbg('%s closing connection'%self)
        for chan in self.chans:
            self.part_chan(chan)
        if self.nick in self.server.users:
            self.server.users.pop(self.nick)

    def event(self,src,type,msg):
        self.send_raw(':%s %s :%s'%(src,type.upper(),msg))

    def send_raw(self,data):
        self.dbg('[%s]Send %s'%(self.host[0],data))
        try:
            self.send_msg(data)
        except:
            self.dbg('err sending to %s'%self)

    def user_mask(self):
        return '%s!anon@%s' %(self.nick,self.server.name)

    def kill(self,reason):
        self.send_notice(self.server.name,'KILLED: %s'%reason)
        self.server.close_user(self)

    def on_pong(self,pong):
        self.last_ping_recv = now()

    def on_ping(self,ping):
        self.dbg(ping)
        ping = ping.split(' ')[0]
        self.send_raw(':%s PONG %s :%s'%(self.server.name,self.server.name,ping))
        self.last_ping_recv = now()

    def send_ping(self):
        self.last_ping_send = now()
        self.send_raw('PING %s'%(self.last_ping_send))


    def join_chan(self,chan):
        chan = chan.lower()
        if chan in self.chans:
            return
        self.server.join_channel(self,chan)

    def part_chan(self,chan):
        chan = chan.lower()
        if chan in self.chans:
            self.server.part_channel(self,chan)

    def timeout(self):
        self.server.close_user(self)

    def _rand_nick(self,l):
        return base64.b32encode(os.urandom(l)).replace('=','')

    def send_num(self,num,data):
        self.send_raw(':%s %s %s %s'%(self.server.name,num,self.nick,data))

    def do_nickname(self,nick):
        if '#' in nick and nick[0] != '#':
            i = nick.index('#')
            trip = util.tripcode(nick[:i],nick[i+1:])
            nick = nick[:i]
            nick += '|' 
            nick += trip[:len(trip)/2]        
        else:
            nick = self._rand_nick(6)
            while self.server.has_user(nick):
                nick = self._rand_nick(6)
                
        return nick

    def got_line(self,inbuffer):
        p = inbuffer.split(' ')
        l = len(p)
        data = inbuffer.lower()
        
        if data.startswith('quit'):
            self.close_when_done()
            return
        if data.startswith('ping'):
            if len(p) != 2:
                return
            self.on_ping(p[1])
            return
        if data.startswith('pong'):
            if len(p) != 2:
                return
            self.on_pong(p[1])
            return
        
        if data.startswith('user') and l > 1:
            self.usr = p[1]

        if data.startswith('nick') and l > 1:
            self.dbg('got nick: %s'%p[1])
            if p[1][0] == '#':
                p[1] = 'skid' + p[1]
            nick = self.do_nickname(p[1])
            if not self.welcomed and len(self.nick) == 0:
                self.nick = p[1]
                self.server.add_user(self)
                self.server.change_nick(self,nick)
            elif len(self.nick) > 0:
                self.server.change_nick(self,nick)
        if not self.welcomed:
            return

        if data.startswith('mode'):
            if len(p) > 1:
                if p[1][0] in ['&','#']:
                    self.send_num(324,'%s +'%(p[1]))

        #if data.startswith('who'):
        #    if len(p) > 1:
        #        if p[1][0] in ['#','&']:
        #            chan = p[1]
        #            if chan in self.chans:
        #                if chan in self.server.chans:
        #                    self.server.chans[chan].send_who(self)
        if data.startswith('part'):
            chans = p[1].split(',')
            for chan in chans:
                self.part_chan(chan)
        if data.startswith('privmsg'):
            c = inbuffer.split(':')
            msg = ''
            for pt in c[1:]:
                msg+= ':%s'%pt
            target = p[1]
            self.server.privmsg(self,target,msg)
        if data.startswith('motd'):
            self.server.send_motd(self)
        if data.startswith('join'):
            if l == 1:
                self.send_raw(461, '%s :Not enough parameters'%p[0])
                return
            chans = p[1].split(',')
            for chan in chans:
                self.join_chan(chan.strip())
        if data.startswith('names'):
            for chan in p[1].split(','):
                if chan in self.chans:
                    self.server[chans].send_who(self)
        if data.startswith('list'):
            self.server.send_list(self)

    def nick_change(self,user,newnick):
        data = ':%s!anon@%s NICK %s'%(user.nick,self.server.name,newnick)
        if user == self:
            data = ':%s NICK %s'%(user,newnick)
        self.send_raw(data)


    def send_msg(self,data):
        pass


BaseUser = User
