from setuptools import find_packages, setup


setup(
    name="quick_tools",
    version="0.1.0",
    description="Small command-line utilities.",
    author="Sadanand Modak",
    python_requires=">=3.8",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    entry_points={
        "console_scripts": [
            "quick-tools=quick_tools.cli:main",
        ]
    },
)
