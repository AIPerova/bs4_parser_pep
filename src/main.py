from collections import defaultdict
from http import HTTPStatus
import logging
import re
from urllib.parse import urljoin
import urllib3

from bs4 import BeautifulSoup
from tqdm import tqdm
import requests
import requests_cache

from configs import configure_argument_parser, configure_logging
from constants import BASE_DIR, INFO, MAIN_DOC_URL, PEP_URL, EXPECTED_STATUS
from outputs import control_output
from utils import get_response, find_tag


def pep(session):
    """Парсинг документации PEP."""
    try:
        response = get_response(session, PEP_URL)
    except urllib3.error.URLError as err:
        logging.error(err.reason)
    if response.status_code != HTTPStatus.OK:
        raise requests.HTTPError(
            f'Ошибка {response.status_code}!'
            'Проблема с доступом к странице.')
    soup = BeautifulSoup(response.text, 'lxml')
    main_table = find_tag(soup, 'section', attrs={'id': 'numerical-index'})
    peps = main_table.find_all('tr')
    statuses = defaultdict(int)
    log_message = ''
    for pep in tqdm(peps[1:]):
        status_main_page = find_tag(pep, 'abbr').text[1:]
        pep_link = find_tag(pep, 'a')['href']
        try:
            response = get_response(session, urljoin(PEP_URL, pep_link))
        except urllib3.error.URLError as err:
            logging.error(err.reason)
        if response.status_code != HTTPStatus.OK:
            raise requests.HTTPError(
                f'Ошибка {response.status_code}!'
                'Проблема с доступом к странице.')
        soup = BeautifulSoup(response.text, 'lxml')
        status_on_page = find_tag(soup, 'abbr').text
        correct_status = EXPECTED_STATUS[status_main_page]
        if status_on_page not in correct_status:
            log_message += INFO.format(urljoin(PEP_URL, pep_link),
                                       status_on_page,
                                       correct_status)
        statuses[status_on_page] += 1
    results = [('Статус', 'Количество')]
    results.extend(list(statuses.items()))
    results.append(('Total', sum(statuses.values())))
    logging.info(log_message)
    return results


def whats_new(session):
    """Поиск новых статей o Python."""
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')
    try:
        response = get_response(session, whats_new_url)
    except urllib3.error.URLError as err:
        logging.error(err.reason)
    if response.status_code != HTTPStatus.OK:
        raise requests.HTTPError(
            f'Ошибка {response.status_code}!'
            'Проблема с доступом к странице.')
    soup = BeautifulSoup(response.text, features='lxml')

    main_div = find_tag(soup, 'section', attrs={'id': 'what-s-new-in-python'})

    div_with_ul = find_tag(main_div, 'div', attrs={'class': 'toctree-wrapper'})

    sections_by_python = div_with_ul.find_all('li',
                                              attrs={'class': 'toctree-l1'})

    results = [('Ссылка на статью', 'Заголовок', 'Редактор, Автор')]
    for section in tqdm(sections_by_python):
        version_a_tag = find_tag(section, 'a')
        href = version_a_tag['href']
        version_link = urljoin(whats_new_url, href)
        response = get_response(session, version_link)
        if response is None:
            continue
        soup = BeautifulSoup(response.text, 'lxml')
        h1 = find_tag(soup, 'h1')
        dl = find_tag(soup, 'dl')
        dl_text = dl.text.replace('\n', ' ')
        results.append(
            (version_link, h1.text, dl_text)
        )

    return results


def latest_versions(session):
    """Поиск ссылок на новую документацию Python."""
    try:
        response = get_response(session, MAIN_DOC_URL)
    except urllib3.error.URLError as err:
        logging.error(err.reason)
    if response.status_code != HTTPStatus.OK:
        raise requests.HTTPError(
            f'Ошибка {response.status_code}!'
            'Проблема с доступом к странице.')
    soup = BeautifulSoup(response.text, 'lxml')
    sidebar = find_tag(soup, 'div', {'class': 'sphinxsidebarwrapper'})
    ul_tags = sidebar.find_all('ul')
    for ul in ul_tags:
        if 'All versions' in ul.text:
            a_tags = ul.find_all('a')
            break
    else:
        raise ValueError('Ничего не нашлось')

    results = [('Ссылка на документацию', 'Версия', 'Статус')]
    pattern = r'Python (?P<version>\d\.\d+) \((?P<status>.*)\)'
    for a_tag in a_tags:
        link = a_tag['href']
        text_match = re.search(pattern, a_tag.text)
        if text_match is not None:
            version, status = text_match.groups()
        else:
            version, status = a_tag.text, ''
        results.append(
            (link, version, status)
        )

    return results


def download(session):
    """Загрузка документации."""
    downloads_url = urljoin(MAIN_DOC_URL, 'download.html')
    try:
        response = get_response(session, downloads_url)
    except urllib3.error.URLError as err:
        logging.error(err.reason)
    if response.status_code != HTTPStatus.OK:
        raise requests.HTTPError(
            f'Ошибка {response.status_code}!'
            'Проблема с доступом к странице.')
    soup = BeautifulSoup(response.text, 'lxml')
    main_tag = find_tag(soup, 'div', {'role': 'main'})
    table_tag = find_tag(main_tag, 'table', {'class': 'docutils'})
    pdf_a4_tag = find_tag(table_tag,
                          'a',
                          {'href': re.compile(r'.+pdf-a4\.zip$')})
    pdf_a4_link = pdf_a4_tag['href']
    archive_url = urljoin(downloads_url, pdf_a4_link)
    filename = archive_url.split('/')[-1]
    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename
    response = session.get(archive_url)

    with open(archive_path, 'wb') as file:
        file.write(response.content)
    logging.info(f'Архив был загружен и сохранён: {archive_path}')


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep,
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')
    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info(f'Аргументы командной строки: {args}')
    session = requests_cache.CachedSession()
    if args.clear_cache:
        session.cache.clear()
    parser_mode = args.mode
    try:
        results = MODE_TO_FUNCTION[parser_mode](session)
        if results is not None:
            control_output(results, args)
    except Exception as err:
        logging.error(f'Сбой в работе программы: {err}',
                      exc_info=True)
    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
