import langchain_core, pkgutil, importlib
print('langchain_core version:', getattr(langchain_core, '__version__', 'no-version'))
print('path:', getattr(langchain_core, '__path__', None))
print('submodules:')
for m in pkgutil.iter_modules(langchain_core.__path__):
    print('  ', m.name)
print('\nTrying to import langchain_core.pydantic_v1:')
try:
    import langchain_core.pydantic_v1 as v1
    print('OK', v1)
except Exception as e:
    print('ERR', type(e), e)