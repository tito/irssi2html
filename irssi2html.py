#!/usr/bin/python
import sys
from collections import defaultdict
from os.path import join, dirname, exists, relpath, realpath, basename
from os import walk, stat, makedirs, sep
from shutil import copy
import json
import jinja2
import math
import re

def hsv2rgb(h, s, v):
    h = float(h)
    s = float(s)
    v = float(v)
    h60 = h / 60.0
    h60f = math.floor(h60)
    hi = int(h60f) % 6
    f = h60 - h60f
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    r, g, b = 0, 0, 0
    if hi == 0: r, g, b = v, t, p
    elif hi == 1: r, g, b = q, v, p
    elif hi == 2: r, g, b = p, v, t
    elif hi == 3: r, g, b = p, q, v
    elif hi == 4: r, g, b = t, p, v
    elif hi == 5: r, g, b = v, p, q
    r, g, b = int(r * 255), int(g * 255), int(b * 255)
    return r, g, b

def write(text):
    sys.stdout.write(text)
    sys.stdout.flush()

colors = {}
gcolor = 0
url_re = re.compile(r"(^|[\n \?])(((http|https)://[\w\#$%&~.\-;:=,?@\[\]+]*)(/[\w\#$%&~/.\-;:=,?@\[\]+]*)?)", re.IGNORECASE | re.DOTALL)
issue_re = re.compile(r'#(\d+)')
revision_re = re.compile(r'(^|\W)r([a-f0-9]{7,32})($|\W)')
words_re = re.compile(r'\w{3,}')
recursive_dict = lambda: defaultdict(recursive_dict)
search_dict = {'__index': []}
url_list = [[]]
stats_nick_messages = {}

class Log(object):
    def __init__(self, filename, input_dir, output_dir):
        super(Log, self).__init__()
        self.lines = None
        self.filename = filename
        self.input_dir = input_dir
        self.output_dir = output_dir

        # determine year + month + day
        self.channel, date, ext = basename(filename).rsplit('.', 2)
        self.month, self.day = date.split('-', 1)
        self.year = dirname(filename).rsplit(sep, 3)[-2]

    def load(self):
        with open(self.filename) as fd:
            self.lines = list(self.readlines(fd))

    def readlines(self, fd):
        for line in fd.readlines():
            line = line.decode('utf8', 'ignore')
            line = self.colorize(self.parse(line))
            if not line:
                continue
            # print line
            yield line

    def colorize(self, line):
        if not line:
            return
        line = list(line)
        nick = line[2]
        if not nick in colors:
            global gcolor
            gcolor = (gcolor + 115) % 360
            c = gcolor
            colors[nick] = (
                ''.join(['%02x' % x for x in hsv2rgb(c, .8, .8)]),
                ''.join(['%02x' % x for x in hsv2rgb(c, .8, .5)]))
        color = colors[nick]
        return line[:2] + [(nick, color[0], color[1])] + line[3:]

    def talk(self, line):
        line = url_re.sub(r'\1<a href="\2">\2</a>', line)
        line = issue_re.sub(r'<a href="https://github.com/kivy/kivy/issues/\1">#\1</a>', line)
        line = revision_re.sub(r'\1<a href="https://github.com/kivy/kivy/commit/\2">r\2</a>\3', line)
        return line

    def parse(self, line):
        # extract time
        if line.startswith('---'):
            return

        # personnal message from the logs
        if line[6:11] == 'Irssi':
            return
        if line[6:9] == '>>>':
            return

        hours, nick, line = line[:5], line[7:17].strip(), line[19:].strip()
        if line.endswith('\n'):
            line = line[:-1]

        if nick:
            if nick[0] == '+':
                nick = nick[1:].strip()
            return ('talk', hours, nick, self.talk(line), line)
        if line[:3] == '>>>':
            if line[4] == '[':
                return
            nick, line = line[4:].split('!', 1)
            return ('enter', hours, nick, line)
        elif line[:3] == '<<<':
            return
        elif line[:1] == '<':
            nick, line = line[4:].split('!', 1)
            return ('leave', hours, nick, line)
        elif line[:1] == '~':
            nickfrom, nickto = line[4:].split(' is now ', 1)
            return ('rename', hours, nickfrom, nickto)
        elif '*.net <-\-> *.split' in line:
            return
        else:
            nick, line = line.split(' ', 1)
            nick = nick.strip()
            if nick == 'ChanServ' or nick.endswith('.freenode.net'):
                return
            return ('status', hours, nick, self.talk(line))

    @property
    def html_fn(self):
        fn = self.filename[len(self.input_dir):]
        if fn.startswith('/'):
            logfn = fn[1:]
        logfn = logfn.replace('#', '')
        return join(self.output_dir, logfn[:-4] + '.html')

    @property
    def link(self):
        fn = relpath(self.html_fn, self.output_dir)
        return fn.replace('#', '%23')

    def relink(self, to):
        fn = relpath(self.html_fn, dirname(to))
        return fn.replace('#', '%23')

    def fill_search(self):
        global search_dict

        if self.lines is None:
            self.read()

        link = self.link
        if link not in search_dict['__index']:
            search_dict['__index'].append(link)
        link_index = search_dict['__index'].index(link)

        for index, line in enumerate(self.lines):
            if line[0] != 'talk':
                continue
            line = line[4]
            words = set(re.findall(words_re, line))
            key = (link_index, index)
            for word in words:
                if word == '__index':
                    continue
                if word not in search_dict:
                    search_dict[word] = []
                if key not in search_dict[word]:
                    search_dict[word].append(key)

    def fill_url(self):
        global search_dict

        if self.lines is None:
            self.read()

        link = self.link
        if link not in url_list[0]:
            url_list[0].append(link)
        link_index = url_list[0].index(link)

        for index, line in enumerate(self.lines):
            if line[0] != 'talk':
                continue
            line = line[4]
            urls = set(re.findall(url_re, line))
            key = (link_index, index)
            for url in urls:
                url = url[1]
                if len(url) < 8:
                    continue
                if 'http://git.io/' in url or '/commit/' in url:
                    continue
                urlkey = (key, url)
                if urlkey not in url_list:
                    url_list.append(urlkey)


class LogGenerator(object):
    def __init__(self, input_dir, output_dir):
        super(LogGenerator, self).__init__()
        self.input_dir = realpath(input_dir)
        self.output_dir = realpath(output_dir)
        templates_dir = join(dirname(__file__), 'templates')
        self.env = jinja2.Environment(loader=jinja2.FileSystemLoader(
            templates_dir))

        # copy standard files
        if not exists(output_dir):
            makedirs(output_dir)
        for fn in ('irclog.css', 'jquery-1.7.2.min.js'):
            copy(join(templates_dir, fn), join(output_dir, fn))

        # load search database
        global search_dict
        fn = join(output_dir, 'search.json')
        if exists(fn):
            write('[ ] Load previous search database...')
            with open(fn) as fd:
                search_dict = json.load(fd)
            write('\r[x] Load previous search database...\n')

        # load url database
        global url_list
        fn = join(output_dir, 'urls.json')
        if exists(fn):
            write('[ ] Load previous URL database...')
            with open(fn) as fd:
                url_list = json.load(fd)
            write('\r[x] Load previous URL database...\n')

    def generate(self):
        logfiles = []

        # get all the files
        write('[ ] Search logs...')
        for logfn in self._search_logs(self.input_dir):
            log = Log(logfn, self.input_dir, self.output_dir)
            logfiles.append(((log.year, log.month, log.day), log))
        write('\r[x] Search logs... found %d\n' % len(logfiles))

        # sort values
        logfiles.sort(key=lambda x: x[0])

        # generate html only if needed
        for index, item in enumerate(logfiles):
            write('\r[ ] Generate %d/%d (%d urls, %d search terms)' % (
                index + 1, len(logfiles), len(url_list), len(search_dict) ))
            date, log = item
            htmlfn = log.html_fn
            # check if it need to be updated
            if exists(htmlfn) and \
                stat(logfn).st_mtime < stat(htmlfn).st_mtime:
                    continue

            # calculate link for navigation (before/after)
            before = after = beforelink = afterlink = None
            if index > 1:
                before = logfiles[index - 1][1]
                beforelink = before.relink(log.html_fn)
            if index < len(logfiles) - 1:
                after = logfiles[index + 1][1]
                afterlink = after.relink(log.html_fn)

            # do the generation
            self.generate_html(log, htmlfn,
                    before=before, after=after,
                    beforelink=beforelink, afterlink=afterlink)

            # fill the dictionnary
            #log.fill_search()
            log.fill_url()

        write('\r[x] Generate %d/%d (%d urls, %d search terms)\n' % (
            index + 1, len(logfiles), len(url_list), len(search_dict) ))

        # generate the index.html
        write('[ ] Generate index...')
        self.generate_index(logfiles)
        write('\r[x] Generate index\n')

        # generate the search
        write('[ ] Generate search...')
        self.generate_search()
        write('\r[x] Generate search\n')

    def generate_index(self, logs):
        indexfn = join(self.output_dir, 'index.html')
        template = self.env.get_template('irc-index.html')

        # do some ordering
        order = recursive_dict()
        for date, log in logs:
            order[log.channel][log.year][log.month][log.day] = log

        text = template.render(logs=order)
        with open(indexfn, 'wb') as fd:
            fd.write(text)

    def generate_html(self, log, htmlfn, **template_args):
        log.load()
        template = self.env.get_template('irc-day.html')
        directory = dirname(htmlfn)
        if not exists(directory):
            makedirs(directory)

        root = relpath(realpath(self.output_dir), realpath(dirname(htmlfn)))
        text = template.render(log=log, root=root, **template_args)
        with open(htmlfn, 'wb') as fd:
            fd.write(text.encode('utf8', 'ignore'))

    def generate_search(self):
        with open(join(self.output_dir, 'urls.json'), 'w') as fd:
            json.dump(url_list, fd)
        with open(join(self.output_dir, 'search.json'), 'w') as fd:
            json.dump(search_dict, fd)

    def _search_logs(self, directory):
        for root, dirnames, filenames in walk(directory):
            for filename in filenames:
                if filename[-4:] == '.log':
                    yield join(root, filename)


if __name__ == '__main__':

    input_dir = sys.argv[1]
    output_dir = 'html'
    if len(sys.argv) > 2:
        output_dir = sys.argv[2]

    gen = LogGenerator(input_dir, output_dir)
    gen.generate()
