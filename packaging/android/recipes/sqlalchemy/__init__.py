from pythonforandroid.recipe import PyProjectRecipe


class SQLAlchemyRecipe(PyProjectRecipe):
    # 2.0.41+ is required for Python 3.14 (p4a ships 3.14): older releases
    # crash at import with "Can't replace canonical symbol for '__firstlineno__'".
    name = 'sqlalchemy'
    version = '2.0.44'
    url = 'https://github.com/sqlalchemy/sqlalchemy/archive/refs/tags/rel_{}.tar.gz'
    depends = ['setuptools']

    @property
    def versioned_url(self):
        return self.url.format(self.version.replace(".", "_"))


recipe = SQLAlchemyRecipe()
