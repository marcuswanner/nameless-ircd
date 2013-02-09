import util

def make_trip(name,code):
    trip = util.tripcode(name,code)
    l = len(trip)
    return '%s|%s' % ( name,trip[:l/2] )


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('user')
    ap.add_argument('passwd')
    ap.add_argument('-quiet',required=False,action='store_const',default=None,const='yes')
    args = ap.parse_args()
  
    if args.quiet != 'yes':
        print ( 'put the following in admin.hash')
        print ('')
    
    print ( make_trip(args.user,args.passwd) )
    if args.quiet != 'yes':
        print ('')
        print ( '/nick %s#%s'% ( args.user,args.passwd ) )
        print ( '/msg adminserv auth' )
        print ( 'you are now admin of your server' )

if __name__ == '__main__':
    main()
