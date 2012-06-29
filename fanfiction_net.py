import re
import urllib
import urllib2

import bs4

_parser = None
try:
    # This isn't lxml for now (even though its faster) because using it as a
    # parser is still untested and I'm unsure if it would yield identical
    # results to html5lib.
    import html5lib
    _parser = 'html5lib'
except ImportError:
    # Don't catch the ImportError: if neither htm5lib nor lxml are available
    # crash ungracefully. The fallback option used by BeautifulSoup 4
    # (HTMLParser) isn't able to handle the HTML (thanks jabagawee!)
    import lxml
    _parser = 'lxml'


_STORYID_REGEX = r"var\s+storyid\s*=\s*(\d+);"
_USERID_REGEX = r"var\s+userid\s*=\s*(\d+);"
# Current form is temporary due to "var storytextid = storytextid=29608487;"
_STORYTEXTID_REGEX = r"storytextid=(\d+);"
_CHAPTER_REGEX = r"var\s+chapter\s*=\s*(\d+);"
_TITLE_REGEX = r"var\s+title\s*=\s*'(.+)';"

# Used to parse the attributes which aren't directly contained in the
# JavaScript and hence need to be parsed manually
_NON_JAVASCRIPT_REGEX = r'Rated:(.+)'
_HTML_TAG_REGEX = r'<.*?>'

# Needed to properly decide if a token contains a genre or a character name
# while manually parsing data that isn't directly contained in the JavaScript
_GENRES = [
    'General', 'Romance', 'Humor', 'Drama', 'Poetry', 'Adventure', 'Mystery',
    'Horror', 'Parody', 'Angst', 'Supernatural', 'Suspense', 'Sci-Fi',
    'Fantasy', 'Spiritual', 'Tragedy', 'Western', 'Crime', 'Family', 'Hurt',
    'Comfort', 'Friendship'
]
_CHAPTER_URL_TEMPLATE = 'http://www.fanfiction.net/s/%d/%d'


def _parse_string(regex, source):
    """Returns first group of matched regular expression as string."""
    return re.search(regex, source).group(1).decode('utf-8')


def _parse_integer(regex, source):
    """Returns first group of matched regular expression as integer."""
    return int(re.search(regex, source).group(1))


def _unescape_javascript_string(string_):
    """Removes JavaScript-specific string escaping characters."""
    return string_.replace("\\'", "'").replace('\\"', '"').replace('\\\\', '\\')


class Story(object):
    def __init__(self, url, opener=urllib2.urlopen):
        source = opener(url).read()
        # Easily parsable and directly contained in the JavaScript, lets hope
        # that doesn't change or it turns into something like below
        self.id = _parse_integer(_STORYID_REGEX, source)
        self.author_id = _parse_integer(_USERID_REGEX, source)
        self.title = urllib.unquote_plus(_parse_string(_TITLE_REGEX, source))

        soup = bs4.BeautifulSoup(source)
        self.author = soup.find('a', href=lambda href: '/u/' in href).string
        self.category = soup('a', {'class': 'xcontrast_txt'})[1].string

        # Tokens of information that aren't directly contained in the
        # JavaScript, need to manually parse and filter those
        tokens = [token.strip() for token in re.sub(_HTML_TAG_REGEX, '', _parse_string(_NON_JAVASCRIPT_REGEX, source)).split(' - ')]

        # Both tokens are constant and always available
        self.rated = tokens[0].split()[1]
        self.language = tokens[1]

        # After those the remaining tokens are uninteresting and looking for
        # either character or genre tokens is useless
        token_terminators = ['Reviews: ', 'Updated: ', 'Published: ']

        # Check if tokens[2] contains the genre
        if tokens[2] in _GENRES or '/' in tokens[2] and all(token in _GENRES for token in tokens[2].split('/')):
            self.genre = tokens[2]
            # tokens[2] contained the genre, check if next token contains the
            # characters
            if not any(tokens[3].startswith(terminator) for terminator in token_terminators):
                self.characters = tokens[3]
            else:
                # No characters token
                self.characters = ''
        elif any(tokens[2].startswith(terminator) for terminator in token_terminators):
            # No genre and/or character was specified
            self.genre = ''
            self.characters = ''
            # tokens[2] must contain the characters since it wasn't a genre
            # (check first clause) but isn't either of "Reviews: ", "Updated: "
            # or "Published: " (check previous clause)
        else:
            self.characters = tokens[2]

        self.reviews = 0
        self.date_updated = None
        for token in tokens:
            if token.startswith('Reviews: '):
                # Replace comma in case the review count is greater than 9999
                self.reviews = int(token.split()[1].replace(',', ''))
            elif token.startswith('Words: '):
                # Replace comma in case the review count is greater than 9999
                self.number_words = int(token.split()[1].replace(',', ''))
            elif token.startswith('Chapters: '):
                self.number_chapters = int(token.split()[1])
            elif token.startswith('Updated: '):
                print token
                self.date_updated = token.split()[1]
            elif token.startswith('Published: '):
                print token
                self.date_published = token.split()[1]

        # In case the story was never updated simply use the publication date
        # for compatibility reasons.
        if not self.date_updated:
            self.date_updated = self.date_published

        # Status is directly contained in the tokens as a single-string
        if 'Complete' in tokens:
            self.status = 'Complete'
        else:
            # FanFiction.Net calls it "In-Progress", I'll just go with that
            self.status = 'In-Progress'

    def get_chapters(self, opener=urllib2.urlopen):
        for number in range(1, self.number_chapters + 1):
            url = _CHAPTER_URL_TEMPLATE % (self.id, number)
            yield Chapter(url, opener)

    # Method alias which allows the user to treat the get_chapters method like
    # a normal property if no manual opener is to be specified.
    chapters = property(get_chapters)


class Chapter(object):
    def __init__(self, url, opener=urllib2.urlopen):
        source = opener(url).read()
        self.story_id = _parse_integer(_STORYID_REGEX, source)
        self.number = _parse_integer(_CHAPTER_REGEX, source)
        self.story_text_id = _parse_integer(_STORYTEXTID_REGEX, source)

        soup = bs4.BeautifulSoup(source, _parser)
        select = soup.find('select', id='chap_select')
        if select:
            # There are multiple chapters available, use chapter's title
            self.title = select.find('option', selected=True).string.split(None, 1)[1]
        else:
            # No multiple chapters, one-shot or only a single chapter released
            # until now; for the lack of a proper chapter title use the story's
            self.title = self.title = urllib.unquote_plus(_parse_string(_TITLE_REGEX, source))
        soup = soup.find('div', id='storytext')
        # Normalize HTML tag attributes
        for hr in soup('hr'):
            del hr['size']
            del hr['noshade']
        self.text = soup.decode()
