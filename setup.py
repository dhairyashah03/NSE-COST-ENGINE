from setuptools import setup, find_packages

setup(
    name="nse-cost-engine",
    version="0.1.0",
    description="Production-grade NSE transaction cost modelling engine",
    author="Dhairya Shah",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=["pyyaml>=6.0"],
    include_package_data=True,
    package_data={"": ["*.yaml"]},
)