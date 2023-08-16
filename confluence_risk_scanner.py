import json
import logging
import os
import subprocess
import sys
import tempfile
from typing import Optional

import click
from atlassian import Confluence
from bs4 import BeautifulSoup
from click.exceptions import ClickException, Exit


class ConfluenceRiskScanner:
    def __init__(self, confluence_url: str, username: str, password: str, pagination_size: int) -> None:
        self.confluence_url = confluence_url.rstrip('/')
        self.pagination_size = pagination_size
        self.client = Confluence(
            url=self.confluence_url,
            username=username,
            password=password,
        )

    def scan_page(self, page_id: int, out) -> None:
        """
        Scans a single page in Confluence Cloud

        Args:
            page_id: Id of the page to scan
            out: file like object to output the results to
        """
        try:
            # get the page content
            page_data = self.client.get_page_by_id(page_id=page_id, expand='body.view')
            self._scan_page_content(page_data, out)
        except Exception:
            # for this recipe we just want to print the exception and continue scanning
            logging.exception(f'Error while scanning page #{page_id}')

    def scan_space(self, space_key: str, out) -> None:
        """
        Scans all pages from a space in Confluence Cloud

        Args:
            space_key: Key of the space to scan
            out: file like object to output the results to
        """
        try:
            self._scan_space(space_key, out)
        except Exception:
            # for this recipe we just want to print the exception and continue scanning
            logging.exception(f'Error while scanning space {space_key}')

    def _scan_space(self, space_key: str, out):

        start = 0
        limit = self.pagination_size

        # Iterate through all the pages in the response and scan each page
        while True:
            response = self.client.get_space_content(
                space_key=space_key, content_type='page', expand='body.view', start=start, limit=limit
            )

            pages = response.get('results') or []
            for page in pages:
                self._scan_page_content(page, out)

            next_link = response.get('_links', {}).get('next')
            if not next_link:
                break

            start += limit

    def _scan_page_content(self, page_data: dict, out):
        page_title = page_data['title']
        page_id = page_data['id']
        content = page_data['body']['view']['value']

        # Note 1: We get in the response from Confluence API as html, which BluBracket cli may not accurately
        # detect risks because of the way they are formatted. So we want to parse the html to text for better detection.

        # Note 2: We may still potentially miss some secrets because of the assignment operators.
        # Since these aren't code files, it is not uncommon to have a secret in the following way
        # Password - abc123

        # Note 3: Confluence uses curly double quotes by default and BluBracket CLI doesn't detect them.
        # password = “abc123”
        soup = BeautifulSoup(content, 'html.parser')

        # Using space as separator because if the risk identifier and value are formatted in a different way,
        # they are parsed into two different lines when using a newline separator
        formatted_content = soup.get_text(separator=' ')

        click.echo(f'scanning page {page_title}')

        # we will output to a temp file
        fd, cli_output_file_path = tempfile.mkstemp()

        try:
            os.close(fd)  # only CLI will write to the file

            # run CLI as a subprocess to scan a single file
            # note: as there is no `--input` parameter, the input data will come from stdin
            cli_cmd = [
                "blubracket",
                # scan-file instructs CLI to scan a single file
                "scan-file",
                # specify the file name as there will be no file on local file system
                "--filename",
                f'{page_title} ({page_id})',
                # found secrets will be stored in `cli_output_file_path`
                "-o",
                cli_output_file_path,
            ]

            with subprocess.Popen(cli_cmd, stdin=subprocess.PIPE, stderr=subprocess.STDOUT) as cli_process:

                # stream the file through CLI
                # doing that allows us to avoid saving the whole file on local file system
                try:
                    cli_process.stdin.write(formatted_content.encode('utf-8'))
                except BrokenPipeError:
                    # if CLI does no support handling of particular files, e.g. binary files
                    # CLI will exit without reading the input data
                    # this will lead to BrokenPipeError in stdin.write(chunk)
                    # 'ignore' it as it is a real error
                    click.echo(f'skipping page {page_title}')

                # note: when `-o` option is specified, `scan-file` command does not produce any output except on errors
                # so it is OK to stream the whole file (input body) first, without consuming the output,
                # and to collect any possible output only later.
                # so, it is OK to call `communicate` here.
                # In case there is a lot of output we would need to collect it asynchronously (in other thread),
                # to avoid a possible deadlock when both input and output pipes will be blocked.
                stdout, _ = cli_process.communicate()
                if stdout:
                    raise Exception(stdout.decode('utf-8', 'replace'))

            # now have the file output, send to the final output file
            with open(cli_output_file_path, 'r') as cli_output_file:
                for secret_line in cli_output_file.readlines():
                    # now ready to store the secret in out
                    secret_json = self._transform_output(secret_line=secret_line, page_data=page_data)
                    out.write(secret_json)
                    out.write('\n')
                    out.flush()

        finally:
            os.remove(cli_output_file_path)

    def _transform_output(self, secret_line: str, page_data: dict) -> str:
        #  each line is a valid json object/dictionary
        secret = json.loads(secret_line)

        # remove some fields that not useful
        secret.pop('auto_dismiss', None)
        secret.pop('line1', None)
        secret.pop('line2', None)
        secret.pop('col1', None)
        secret.pop('col2', None)

        # add some new fields that are useful
        secret['page_title'] = page_data['title']
        secret['page_id'] = page_data['id']

        # Use tinyui link if present, otherwise use the webui link
        tinyui_link = page_data.get('_links', {}).get('tinyui')
        webui_link = page_data.get('_links', {}).get('webui')

        if tinyui_link:
            secret['page_link'] = f'{self.client.url}{tinyui_link}'
        elif webui_link:
            secret['page_link'] = f'{self.client.url}{webui_link}'

        return json.dumps(secret)


@click.command()
@click.option(
    '--url',
    type=click.STRING,
    help='Confluence Cloud URL',
    required=True,
)
@click.option(
    '--page-id',
    type=click.INT,
    help='Id of the page to scan',
)
@click.option(
    '--space-key',
    type=click.STRING,
    help='Key of the space to scan',
)
@click.option(
    '--pagination-size',
    type=click.INT,
    default=10,
    help='Maximum number of pages to scan at a time, only applicable when scanning a space',
)
@click.option(
    '--output',
    '-o',
    type=click.File("w"),
    default=sys.stdout,
    help='Output file name to store found risks. Defaults to stdout',
)
def scan_confluence(url: str, page_id: Optional[int], space_key: Optional[str], pagination_size: int, output):
    """
    Scans a page or space in Confluence Cloud for secrets using BluBracket CLI.

    Set the credentials as environment variables:

    ATLASSIAN_ACCOUNT_EMAIL - Email associated with the Atlassian account

    ATLASSIAN_API_TOKEN - Atlassian API token.
    Create one from https://id.atlassian.com/manage-profile/security/api-tokens
    """

    username = os.environ.get('ATLASSIAN_ACCOUNT_EMAIL')
    password = os.environ.get('ATLASSIAN_API_TOKEN')

    if not username or not password:
        raise ClickException('Please set the ATLASSIAN_ACCOUNT_EMAIL and ATLASSIAN_API_TOKEN environment variables')

    scanner = ConfluenceRiskScanner(
        confluence_url=url, username=username, password=password, pagination_size=pagination_size
    )

    if page_id:
        scanner.scan_page(page_id=page_id, out=output)
    elif space_key:
        scanner.scan_space(space_key=space_key, out=output)
    else:
        click.echo("Either --page-id or --space-key is required")
        raise Exit(code=1)


if __name__ == '__main__':
    scan_confluence()
