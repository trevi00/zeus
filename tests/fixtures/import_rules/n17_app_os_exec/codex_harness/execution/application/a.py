import os


def go():
    os.execv('/bin/true', ['true'])
