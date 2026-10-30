"""Free Python hosting entry point: python main.py. No Docker or Node.js."""
import os
os.environ.setdefault('GOMEMLIMIT','96MiB')
os.environ.setdefault('GOGC','50')
from watcher.lite_app import main

if __name__=='__main__':
    main()
