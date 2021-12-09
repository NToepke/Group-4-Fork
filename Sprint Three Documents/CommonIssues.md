# Common Issues

## Python version
More than likely when you see that you must install Python 3, you simply go to their website and download the newest version. However, this program uses older versions as the newest version seldom allows for the use of machine learning. Therefore, if you run into issues with your system's Python, update your Python version to at least 3.8. Python can be downloaded [here](https://www.python.org/downloads/)

### Ubuntu Python Command Line Installation
Installation assumes you are using a sudo user  
#### Install Required Dependencies
> $ sudo apt update  
> $ sudo apt install software-properties-common
#### Install deadsneakes PPA
deadsnakes PPA allows for multiple installs of python  
> $ sudo add-apt-repository ppa:deadsnakes/ppa
#### Install python
> $ sudo apt install python3.8  
> (Or pythonX.X for your desired version)
