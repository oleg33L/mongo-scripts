#!/usr/bin/python

import sys
import socket
from time import strptime , strftime
import re
import datetime
import zlib,gzip
import StringIO

import threading
import Queue

import pymongo

import simples3
import settings # for s3

class LineParser:
    def __init__(self,regex,names):
        self._regex = regex
        self._names = names
        self._patt = re.compile( regex )

    def parse(self,line):
        m = self._patt.match(line)
        if not m:
            print( "can't parse line: " + line )
            return None

        result = [m.group(1+n) for n in range(len(self._names))]

        d = {}
        for ( name , val ) in zip( self._names , result ):
            d[ name ] = val

        return d


normalParser = LineParser( r'(\S+) (\S+) \[(.*?)\] (\S+) (\S+) ' \
                               r'(\S+) (\S+) (\S+) "([^"]+)" ' \
                               r'(\S+) (\S+) (\S+) (\S+) (\S+) (\S+) ' \
                               r'"([^"]+)" "([^"]+)"' , 
                           ("bucket_owner", "bucket", "datetime", "ip", "requestor_id", 
                            "request_id", "operation", "uri-stem", "http_method_uri_proto", "status", 
                            "s3_error", "bytes_sent", "object_size", "total_time", "turn_around_time",
                            "Referer", "User-Agent") )


class W3CParser:
    def __init__(self):
        self.p = re.compile("\s+")

    def parse(self,line):
        if line.startswith( "#Version:" ):
            return None
        
        if line.startswith( "#Fields: " ):
            x = self.p.split( line[9:] )
            self.names = []
            for z in x:
                if z.startswith( "cs-" ):
                    z = z[3:]
                if z.startswith( "cs(" ):
                    z = z[3:]
                    z = z.rstrip( ")" )
                if z.startswith( "c-" ):
                    z = z[2:]
                if z.startswith( "sc-" ):
                    z = z[3:]
                self.names.append( z )
            return None
        
        x = self.p.split( line )

        d = {}
        for ( name , val ) in zip( self.names , x ):
            d[name] = val
        return d
                           

def getAllDays( start=(2009,1) ):
    a = []
    y = start[0]
    today = datetime.datetime.today()
    while y <= today.year:

        maxMonth = 13
        if y == today.year:
            maxMonth = today.month + 1

        minMonth = 1
        if y == start[0]:
            minMonth = start[1]

        for m in range( minMonth , maxMonth ):
            for d in range( 31 ):
                try:
                    datetime.datetime(y,m,d)
                    t = (y,m,d)
                    a.append( t )
                except Exception,e:
                    pass
                
        y = y + 1
    a.reverse()
    return a


def getWeek( y,m,d ):
    d = datetime.datetime(y,m,d)
    delta = datetime.timedelta(d.weekday())
    d = d - delta
    return (d.year,d.month,d.day)


def addGZ( n ):
    return [ n , n + ".gz" ]

badEndings = []
for x in [ "Packages" , "Packages.bz2" , "Release" , "Sources" , 
           ".xml" , ".dsc" , ".md5" , ".gpg" 
           , ".pdf" , ".html" , ".png" , ".conf" ]:
    badEndings.append( x )
    badEndings.append( x + ".gz" )

badStrings = [ "misc/boost" ]

badStarts = [ "log/" , "stats/" , "log-fast/" ]

goodEndings = [ ".tar.gz" , ".tgz" , ".zip" , ".deb" , ".rpm" ]


# -1 bad, 0 unknown 1 good
def decide( key ):
    if key == "-":
        return -1
    for e in badEndings:
        if key.endswith( e ):
            return -1
    for e in badStrings:
        if key.find( e ) >= 0:
            return -1
    for e in goodEndings:
        if key.endswith( e ):
            return 1
    for e in badStarts:
        if key.startswith( e ):
            return -1
    return 0


def skipLine( data ):
    if data["ip"] == "64.70.120.90":
        return True

    if data["User-Agent"].find( "bot" ) >= 0:
        return True

    if data["status"] != "200":
        return True
       
    key = data["uri-stem"]

    x = decide( key )
    if x < 0:
        return True
    
    if x == 0:
        print( "skipping unknown: " + key )
        return True

    return False


conn = pymongo.Connection()
db = conn.mongousage

def getReverse( ip ):
    x = db.ips.find_one( { "_id" : ip } )
    if not x:
        x = { "_id" : ip }
        try:
            x["r"] = r = socket.gethostbyaddr( ip )[0]
            db.ips.insert( x )
        except Exception,e:
            return None

    return x["r"]

def getReverseDomain( h ):
    h = h.split(".")
    h.reverse()
    
    max = 1

    if len(h) > 1:
        max = 2
        
    if len(h) > 2 and len(h[0]) <= 2:
        max = 3
        
    s = h[0:max]
    s.reverse()
    s = ".".join(s)

    return s

def doFetch( s , key ):
    err = None
    data = None

    for x in range(10):
        try:
            #data = s.get(key,timeout=2).read()
            data = s.get(key).read()
            break
        except Exception,e:
          err = e
          print( key + "\t" + str(e) )

    if not data:
        raise err

    if key.endswith( ".gz" ):
        data = gzip.GzipFile('', 'rb', 9, StringIO.StringIO(data)).read()

    return data

def handleFile( s , parser , key , y , m , d ):
    print( "\t" + key )
    if db.files.find_one( { "_id" : key } ):
        return

    lineNumber = 0

    data = doFetch( s , key )

    for line in data.splitlines():
        lineNumber = lineNumber + 1

        p = parser.parse( line )
        if not p:
            continue

        if skipLine( p ):
            continue;

        id = key + "-" + str(lineNumber)
        p["_id"] = id
        p["raw"] = line
        p["date"] = { "year" : y , "month" : m , "day" : d }
        w = getWeek( y , m , d )
        p["week"] = { "year" : w[0] , "month" : w[1] , "day" : w[2] }
        p["fromFile"] = key
        p["os"] = p["uri-stem"].partition( "/" )[0]
        r = getReverse( p["ip"] )
        if r:
            p["reverse"] = r
            p["reverseDomain"] = getReverseDomain( r )
        db.downloads.update( { "_id" : id } , p , upsert=True )
    print( "\t\t" + str(lineNumber) )
    db.files.insert( { "_id" : key , "when" : datetime.datetime.today() } )


def workerThread( parser , q , threadNum ):
    s = simples3.S3Bucket( settings.bucket , settings.id , settings.key )

    try:
        while True:
            filter,y,m,d = q.get_nowait()
            for (key, modify, etag, size) in s.listdir(prefix=filter):
                print( "thread:" + str(threadNum) + " " + key )
                handleFile( s , parser , key , y , m , d )
    except Queue.Empty,e:
        pass


def doBucket( fileNameBuilder , parser , start ):
    q = Queue.Queue()
    
    for y,m,d in getAllDays(start):
        q.put( (fileNameBuilder( y , m , d ),y,m,d) )

    allThreads = []
    for x in range(10):
        allThreads.append( threading.Thread( target=workerThread , args=(parser,q,x) ) )

    for t in allThreads:
        t.start()
    for t in allThreads:
        t.join()


def normalFileNameBuilder(y,m,d):
    return "log/access_log-%d-%02d-%02d" % ( y , m , d )

def cloudfrontFileNameBuilder(y,m,d):
    return "log-fast/E22IW8VK01O2RF.%d-%02d-%02d" % ( y , m , d )

doBucket( normalFileNameBuilder , normalParser , ( 2009 , 2 ) )
doBucket( cloudfrontFileNameBuilder , W3CParser() , ( 2010 , 7 ) )

