==========
API Levels
==========

.. currentmodule:: werkzeug

Werkzeug is intended to be a utility rather than a framework.  Because of that
the user-friendly API is separated from the lower-level API so that Werkzeug
can easily be used to extend another system.

All the functionality the :class:`Request` and :class:`Response` objects (aka
the "wrappers") provide is also available in small utility functions.

Example
=======

This example implements a small `Hello World` application that greets the
user with the name entered.

.. code-block:: python

    from markupsafe import escape
    from werkzeug.wrappers import Request, Response

    @Request.application
    def hello_world(request):
        result = ['<title>Greeter</title>']
        if request.method == 'POST':
            result.append(f"<h1>Hello {escape(request.form['name'])}!</h1>")
        result.append('''
            <form action="" method="post">
                <p>Name: <input type="text" name="name" size="20">
                <input type="submit" value="Greet me">
            </form>
        ''')
        return Response(''.join(result), mimetype='text/html')

Alternatively the same application could be used without request and response
objects but by taking advantage of the parsing functions werkzeug provides::

    from markupsafe import escape
    from werkzeug.formparser import parse_form_data

    def hello_world(environ, start_response):
        result = ['<title>Greeter</title>']
        if environ['REQUEST_METHOD'] == 'POST':
            form = parse_form_data(environ)[1]
            result.append(f"<h1>Hello {escape(form['name'])}!</h1>")
        result.append('''
            <form action="" method="post">
                <p>Name: <input type="text" name="name" size="20">
                <input type="submit" value="Greet me">
            </form>
        ''')
        start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8')])
        return [''.join(result).encode('utf-8')]

High or Low?
============

Usually you want to use the high-level layer (the request and response
objects).  But there are situations where this might not be what you want.

For example you might be maintaining code for an application written in
Django or another framework and you have to parse HTTP headers.  You can
utilize Werkzeug for that by accessing the lower-level HTTP header parsing
functions.

Another situation where the low level parsing functions can be useful are
custom WSGI frameworks, unit-testing or modernizing an old CGI/mod_python
application to WSGI as well as WSGI middlewares where you want to keep the
overhead low.
