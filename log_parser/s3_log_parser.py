#!/usr/bin/env python
######################################################
# -*- coding: utf-8 -*-
# File Name: s3_log_parser.py
# Author: James Hong & Qian Li
# Created Date: 2017-10-28
# Description: Parse CloudWatch logs
######################################################

import argparse
import json
import os
import re
import sys
import boto3
import gzip
import numpy as np
import shutil
import time

# need to install python-dateutil
import dateutil.parser

from collections import OrderedDict

TEMP_INPUT = 'download_log.gz'
OUTPUT_DIR = './'

def get_args():
  parser = argparse.ArgumentParser()
  parser.add_argument('--bucket', '-b', type=str, required=True,
            help='S3 bucket where logs files are stored')
  parser.add_argument('--prefix', '-p', type=str, required=True,
            help='S3 log files prefix')
  parser.add_argument('--expname', '-e', type=str, required=False,
            help='Experiment name, eg. example3_138_50_50')
  parser.add_argument('--outfile', '-o', type=str, required=True,
            help='File to save parsed output')
  return parser.parse_args()


class StatsObject(object):

  def __init__(self, expname=None):
    self.numLambdas = 0
    self.totalLogs = 0
    if expname is not None:
      self.validLambda = False
    else:
      self.validLambda = True
    self.expName = expname
    self.data = OrderedDict()

  def incrementNumLambdas(self):
    self.totalLogs += 1
    if self.validLambda:
      self.numLambdas += 1
      if self.expName is not None:
        self.validLambda = False
      else:
        pass

  def record_key_value(self, k, v):
    if k not in self.data:
      self.data[k] = []
    self.data[k].append(v)

  def print_stats(self):
    print 'Parsed %d lambda logs out of %d logs' % (self.numLambdas, 
                                                    self.totalLogs)
    for k, v in self.data.iteritems():
      print k
      print '  mean:', np.mean(v)
      print '  stdev:', np.std(v)
      print '  median:', np.median(v)
      print '  min:', min(v)
      print '  max:', max(v)
      print '  10th:', np.percentile(v, 10)
      print '  25th:', np.percentile(v, 25)
      print '  75th:', np.percentile(v, 75)
      print '  90th:', np.percentile(v, 90)
      print '  95th:', np.percentile(v, 95)
      print '  99th:', np.percentile(v, 99)

  def dump_parsed_values(self, outfile):
    print >> sys.stderr, 'Writing parsed results to', outfile
    with open(outfile, 'w') as ofs:
      json.dump(self.data, ofs)


REPORT_RE = re.compile(r'Duration: ([\d.]+) ms[\s]+Billed Duration: (\d+) ms[\s]+Memory Size: (\d+) MB[\s]+Max Memory Used: (\d+) MB')

def parse_line(line, stats):
  if stats.expName and stats.expName in line:
    stats.validLambda = True
  
  if 'START' in line:
    timeStr, _ = line.split(' ', 1)  
    parsedDate = dateutil.parser.parse(timeStr)
    stats.record_key_value('start-time', time.mktime(parsedDate.timetuple()))

  if 'END' in line:
    timeStr, _ = line.split(' ', 1)
    parsedDate = dateutil.parser.parse(timeStr)
    stats.record_key_value('end-time', time.mktime(parsedDate.timetuple()))

  if stats.validLambda:
    if 'Timelist:' in line:
      timelistObj = None
      try:
        _, timelist = line.split('Timelist:', 1)
        timelistObj = json.loads(json.loads(timelist.strip()))
      except Exception as e:
        try:
          timelistObj = json.loads(timelist)
        except Exception as e:
          print >> sys.stderr, e, line
        
      for k, v in timelistObj.iteritems():
        stats.record_key_value(k, v)

    matchObj = REPORT_RE.search(line)
    if matchObj is not None:
      duration = float(matchObj.group(1))
      billedDuration = int(matchObj.group(2))
      memorySize = int(matchObj.group(3))
      maxMemoryUsed = int(matchObj.group(4))

      stats.record_key_value('duration', duration)
      stats.record_key_value('billed-duration', billedDuration)
      stats.record_key_value('memory-size', memorySize)
      stats.record_key_value('max-memory-used', maxMemoryUsed)
      stats.incrementNumLambdas()

def ensure_clean_state(downloadDir=None):
  if downloadDir is not None:
    if os.path.exists(downloadDir):
      shutil.rmtree(downloadDir)
    os.mkdir(downloadDir)
  else:
    downloadDir = './'
  return downloadDir

def main(args):
  downloadDir = args.prefix.split('/')[0]
  downloadFile = os.path.join(downloadDir, TEMP_INPUT)
  downloadDir = ensure_clean_state(downloadDir)

  print >> sys.stderr, 'Local file: ', downloadFile
  print >> sys.stderr, 'Bucket: ', args.bucket
  print >> sys.stderr, 'Prefix: ', args.prefix
  print >> sys.stderr, 'Experiment: ', args.expname

  stats = StatsObject(args.expname)

  s3 = boto3.resource('s3')
  inputBucket = args.bucket
  inputPrefix = args.prefix

  # We need to fetch file from S3
  logsBucket = s3.Bucket(inputBucket)

  for obj in logsBucket.objects.filter(Prefix=inputPrefix):
    objKey = obj.key
    if objKey.endswith('.gz'):
      print >> sys.stderr, 'Parsing', objKey
      s3.Object(logsBucket.name, objKey).download_file(downloadFile)
      try:
        with gzip.open(downloadFile, 'rb') as logFile:
          for line in logFile:
            parse_line(line, stats)

      except Exception as e:
        print >> sys.stderr, e

  print('S3 Bucket: {}'.format(args.bucket))
  print('File Prefix: {}'.format(args.prefix))
  print('Experiment: {}'.format(args.expname))
  stats.print_stats()
  if args.outfile is not None:
    stats.dump_parsed_values(args.outfile)

if __name__ == '__main__':
  main(get_args())
