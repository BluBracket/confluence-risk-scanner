import logging
import subprocess

import click


@click.command()
# specify command arguments and options
# @click.argument('directory', type=click.Path(exists=True, file_okay=False, resolve_path=True))
# @click.option(
#    '--output',
#    '-o',
#    type=click.File("w"),
#    default=sys.stdout,
#    help='Output file name to store found risks. Defaults to stdout',
# )
def scan(directory, output):
    """
    ...
    """

    # get a list of files/entities to scan
    # then call scan_file for each entity


def scan_file(path, root_dir, out):
    """
    Scans a single file

    Args:
        path: path to a file to scan
        root_dir: top-level directory to scan
        out: file like object to output the results to

    Returns:

    """
    try:
        _scan_file(path, root_dir, out)
    except Exception:
        # for this recipe we just want to print the exception and continue scanning
        logging.exception(f'Error while scanning {path}')


def _scan_file(path, root_dir, out):

    click.echo(f'scanning {path}')

    # check if the file needs to be scanned
    # if not, exit

    # run CLI as a subprocess to scan a single file
    # note: depends on the input might need to provide `--filename` param, e.g. see AWS S3 recipe
    cli_cmd = [
        "blubracket",
        # scan-file instructs CLI to scan a single file
        "scan-file",
        # file to scan
        # note: no need to use --filename parameter as `path` will be used
        "--input",
        path,
    ]

    with subprocess.Popen(cli_cmd, stdin=None, stdout=subprocess.PIPE) as cli_process:
        try:
            _get_and_process_risks(cli_process.stdout, out)
        except BrokenPipeError:
            # CLI might not support handling of particular archive files,
            # in that case CLI will exit without reading the input data
            # this will lead to BrokenPipeError in cli_process.stdout.readlines()
            # 'ignore' it as it is a real error
            click.echo(f'skipping {path}')


def _get_and_process_risks(input_file, out):

    for risk_line in input_file.readlines():

        risk_line = risk_line.decode('utf-8')

        # get risk info
        # risk = json.loads(risk_line)

        # process risk, e.g. write to out file
        # out.write(risk_line)
        # out.flush()


if __name__ == '__main__':
    scan()
