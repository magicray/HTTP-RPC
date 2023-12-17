import time
from distutils.core import setup

setup(
  name='http-rpc',
  packages=['httprpc'],
  scripts=['bin/httprpc-sign-cert'],
  version=time.strftime('%Y%m%d'),
  description='A minimal RPC server using HTTP',
  long_description='HTTP for transport and mTLS for auth',
  author='Bhupendra Singh',
  author_email='bhsingh@gmail.com',
  url='https://github.com/magicray/HTTP-RPC',
  keywords=['http', 'rpc', 'mTLS', 'TLS']
)
