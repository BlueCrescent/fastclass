#!/usr/bin/env python
#
# fastclass - fc_download.py
#
# Christian Werner, 2018-10-23
#
# TODO:
#  - print report (images per class etc)
#  - check if we need grace periods to avoid blocking

import click
import glob
from icrawler import ImageDownloader
from icrawler.builtin import GoogleImageCrawler, BingImageCrawler, BaiduImageCrawler
import logging
import os
import shutil
import tempfile
import timeit
from typing import List, Dict

from . deduplicate import remove_dups
from . imageprocessing import resize
from . misc import sanitize_searchstring

EPILOG = """::: FastClass fcd :::\r
\r
...an easy way to crawl the net for images when building a\r
dataset for deep learning.\r
\r
Example: fcd -c GOOGLE -c BING -s 224 example/guitars.csv

"""

class ImageLog:
    """Dummy class to attach registry of source urls to ImageDownloader"""
    registry = {}

class CustomDownloader(ImageDownloader, ImageLog):
    def process_meta(self, task):
        ImageLog.registry[task['filename']] = task['file_url']

def crawl_google(folder: str, search: str, maxnum: int, num_threads: int):
    google_crawler = GoogleImageCrawler(downloader_cls=CustomDownloader,
                                        log_level=logging.CRITICAL,
                                        feeder_threads=1,
                                        parser_threads=1,
                                        downloader_threads=num_threads,
                                        storage={'root_dir': folder})

    google_crawler.crawl(keyword=search, offset=0, max_num=maxnum,
                         min_size=(200,200), max_size=None, file_idx_offset='auto')

def crawl_bing(folder: str, search: str, maxnum: int, num_threads: int):
    bing_crawler = BingImageCrawler(downloader_cls=CustomDownloader,
                                    log_level=logging.CRITICAL,
                                    downloader_threads=num_threads,
                                    storage={'root_dir': folder})
    bing_crawler.crawl(keyword=search, filters=None, offset=0, max_num=maxnum, file_idx_offset='auto')

def crawl_baidu(folder: str, search: str, maxnum: int, num_threads: int):
    baidu_crawler = BaiduImageCrawler(downloader_cls=CustomDownloader,
                                      log_level=logging.CRITICAL,
                                      downloader_threads=num_threads,
                                      storage={'root_dir': folder})
    baidu_crawler.crawl(keyword=search, offset=0, max_num=maxnum,
                        min_size=(200,200), max_size=None, file_idx_offset='auto')

def crawl_run(c: str, folder: str, search: str, maxnum: int, num_threads: int):
    if c == 'GOOGLE':
        crawl_google(folder, search, maxnum, num_threads)
    elif c == 'BING':
        crawl_bing(folder, search, maxnum, num_threads)
    elif c == 'BAIDU':
        crawl_baidu(folder, search, maxnum, num_threads)

def crawl(folder: str, search: str, maxnum: int, num_threads: int, crawlers: [List[str]] = ['GOOGLE', 'BING', 'BAIDU']) -> Dict[str, str]:
    """Crawl web sites for images"""
    print('(1) Crawling ...')
    # prepare folders
    os.makedirs(folder, exist_ok=True)
    sources = {}

    for c in crawlers:
        print(f'    -> {c}', end='', flush=True)
        run_command = lambda : crawl_run(c, folder, search, maxnum, num_threads)
        runtime = timeit.timeit(run_command, 'gc.enable()', number=1)# / float((10**6))
        print(f' ({runtime:.2f} sec)')

    return {k: v for k, v in CustomDownloader.registry.items() if k is not None}

def main(infile: str, size: int, crawler: List[str], keep: bool, maxnum: int, num_threads: int, outpath: str):
    SIZE=(size,size)
    classes = []

    if 'ALL' in crawler:
        crawler = ['GOOGLE', 'BING', 'BAIDU']

    if os.path.isdir(outpath) or (keep and os.path.isdir(outpath+'.raw')):
        outnames = outpath + (('" or "' + outpath + '.raw') if keep else "")
        print(f'Directory "{outnames}" exists. Would you like to overwrite the directory? [y/n]')
        choice = input().lower()
        while (not (choice is 'y' or 'n')):
            print("Please reply with 'y' or 'n'")
            choice = input().lower()
        if (choice == 'y'):
            shutil.rmtree(outpath)
            if keep and os.path.isdir(outpath+'.raw'):
                shutil.rmtree(outpath+'.raw')
        else:
            exit(-1)

    os.makedirs(outpath)
    print(f'INFO: final dataset will be located in {outpath}')

    with tempfile.TemporaryDirectory() as tmp:
        for lcnt, line in enumerate(infile):
            if lcnt > 0:
                no_cols = line[:-1].count(',')+1
                if no_cols>1:
                    search_term, remove_terms = line[:-1].split(',')
                else:
                    search_term = line[:-1]
                    remove_terms = None
                classes.append((search_term, remove_terms))
                
        for i, (search_term, remove_terms) in enumerate(classes):
            print(f'[{i+1}/{len(classes)}] Searching: >> {search_term} <<')
            out_name = sanitize_searchstring(search_term, rstring=remove_terms)
            raw_folder = os.path.join(tmp, out_name)

            source_urls = crawl(raw_folder, search_term, maxnum, num_threads, crawlers=crawler)
            remove_dups(raw_folder)

            # resize
            out_resized = os.path.join(outpath, out_name)
            os.makedirs(out_resized, exist_ok=True)

            files = sorted(glob.glob(raw_folder+'/*'))

            source_urls = resize(files, outpath=out_resized, size=SIZE, urls=source_urls)

            # write report file
            with open(out_resized + '.log', 'w', encoding="utf-8") as log:
                log.write('image,source\n')
                for item in source_urls:
                    log.write(','.join([item, source_urls[item]]) + '\n')

        if keep:
            shutil.copytree(tmp, outpath+'.raw')


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])
click.Context.get_usage = click.Context.get_help

@click.command(context_settings=CONTEXT_SETTINGS, epilog=EPILOG)

@click.option('-c', '--crawler', default=['ALL'],
              type=click.Choice(['ALL','GOOGLE', 'BING', 'BAIDU']),
              show_default=True, multiple=True,
              help='selection of crawler (multiple invocations supported)')

@click.option('-k', '--keep',  default=False, is_flag=True, show_default=True,
              help='keep original results of crawlers (copy them to .raw folder')

@click.option('-m', '--maxnum', default=1000, show_default=True, type=int,
              help='maximum number of images per crawler (lower is faster, 1000 is max)')

@click.option('-s', '--size',  default=299, show_default=True, type=int,
              help='image size for rescaling. Set to 0 to keep original size.')

@click.option('-t', '--num_threads',  default=4, show_default=True, type=int,
              help='number of threads for crawling.')

@click.option('-o', '--outpath',  default='dataset', show_default=True,
              help='name of output directory')

@click.argument('infile', type=click.File('r'), required=True)

def cli(infile, size, crawler, keep, maxnum, num_threads, outpath):
    main(infile, size, crawler, keep, maxnum, num_threads, outpath)

if __name__ == "__main__":
    cli()
