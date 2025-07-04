# khoj-sync
Forked from https://gist.github.com/dj311/fad8666c361261ed4af68285a233250a.   
Add some new features like:  
 - support api-keys  
 - sync once  
 - set EXCLUDED DIRs  
 - specify dirs to sync from command line or ini file  
 - list files to sync  
 - sync a file list  
and so on. Now it is a powerful sync tool for khoj.  

## Install  
Download or pull or copy the py file to your local device, yes, only the py file.  
Then run   
```pip install docopt```  
and  
```pip install requests```  
to install dependencies.  

## Usage  
```
Usage:  
    khoj-sync [-v | --verbose] init <server> [--api-key=<key>] [--sync-dir=<dir>]  
    khoj-sync [-v | --verbose] sync [--once] [--sync-dir=<dir>] [--files-list=<file>]  
    khoj-sync [-v | --verbose] list [--sync-dir=<dir>] [--files-list=<file>]  
    khoj-sync (-h | --help)  
    khoj-sync --version  
  
Options:  
    -h --help            Show this screen.  
    -v --verbose         Tell me everything you do in excruciating detail.  
    --once               Run sync only once, then exit (don't continuously sync).  
    --api-key=<key>      API key for authentication with the Khoj server.  
    --sync-dir=<dir>     Directory to sync (default: current directory).  
    --files-list=<file>  Path to a file containing a list of files to sync (one per line).  
```

## Files
- khoj-sync.py : This script
- khoj-sync.ini: The configuration file, generated by `python khoj-sync.py init ...` command, will not overwrite if file exist.
- khoj-sync.log: The sync history

### This script is modified by llm, from [dj311](https://gist.github.com/dj311) 's original [work](https://gist.github.com/dj311/fad8666c361261ed4af68285a233250a)
