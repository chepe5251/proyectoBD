CREATE DATABASE biblioteca;
GO
USE biblioteca;
GO

-- =============================================
-- Schemas
-- =============================================

CREATE SCHEMA catalogo;
GO
CREATE SCHEMA operaciones;
GO
CREATE SCHEMA personas;
GO

-- =============================================
-- Tablas
-- =============================================

-- Usuarios registrados en el sistema de biblioteca
-- password_hash: SHA-256 de la contraseña del usuario (64 caracteres hex)
-- rol: determina qué login de SQL Server usará la sesión ('admin', 'operativo', 'usuario')
CREATE TABLE personas.usuarios (
    id_usuario       INT IDENTITY(1,1) PRIMARY KEY,
    nombre_usuario   VARCHAR(100) NOT NULL,
    apellido_usuario VARCHAR(100) NOT NULL,
    correo           VARCHAR(150) UNIQUE NOT NULL,
    telefono         VARCHAR(20),
    password_hash    VARCHAR(72)  NOT NULL,  -- bcrypt hash (60 chars)
    rol              VARCHAR(20)  NOT NULL DEFAULT 'usuario'
);
GO

-- Autores disponibles en el catalogo
CREATE TABLE catalogo.autores (
    id_autor       INT IDENTITY(1,1) PRIMARY KEY,
    nombre_autor   VARCHAR(100) NOT NULL,
    apellido_autor VARCHAR(100) NOT NULL,
    nacionalidad   VARCHAR(100)
);
GO

-- Categorias para clasificar los libros
CREATE TABLE catalogo.categorias (
    id_categoria     INT IDENTITY(1,1) PRIMARY KEY,
    nombre_categoria VARCHAR(100) NOT NULL,
    descripcion      VARCHAR(200)
);
GO

-- Libros del catalogo, vinculados a un autor y una categoria
CREATE TABLE catalogo.libros (
    id_libro        INT IDENTITY(1,1) PRIMARY KEY,
    titulo          VARCHAR(200) NOT NULL,
    ano_publicacion INT,
    id_autor        INT NOT NULL,
    id_categoria    INT NOT NULL,
    CONSTRAINT fk_libro_autor
        FOREIGN KEY (id_autor) REFERENCES catalogo.autores(id_autor),
    CONSTRAINT fk_libro_categoria
        FOREIGN KEY (id_categoria) REFERENCES catalogo.categorias(id_categoria)
);
GO

-- Registro de prestamos y devoluciones
-- estado: 1 = libro prestado, 0 = devuelto
CREATE TABLE operaciones.prestamos (
    id_prestamo      INT IDENTITY(1,1) PRIMARY KEY,
    id_usuario       INT  NOT NULL,
    id_libro         INT  NOT NULL,
    fecha_prestamo   DATE NOT NULL,
    fecha_devolucion DATE,
    estado           BIT  NOT NULL,
    CONSTRAINT fk_prestamo_usuario
        FOREIGN KEY (id_usuario) REFERENCES personas.usuarios(id_usuario),
    CONSTRAINT fk_prestamo_libro
        FOREIGN KEY (id_libro) REFERENCES catalogo.libros(id_libro)
);
GO

-- =============================================
-- Seguridad: roles, logins y usuarios de motor
-- Estos logins son internos de SQL Server.
-- La app los usa según el rol del usuario autenticado.
-- =============================================

CREATE ROLE rol_admin;
GO
CREATE ROLE rol_usuario;
GO
CREATE ROLE rol_operativo;
GO

-- Login auxiliar: solo puede ejecutar personas.autenticar_usuario.
-- La app lo usa para verificar credenciales antes de abrir la sesion operacional.
CREATE LOGIN login_app       WITH PASSWORD = 'App#2026!',       CHECK_POLICY = ON;
GO
CREATE LOGIN login_admin     WITH PASSWORD = 'Admin#2026!',     CHECK_POLICY = ON;
GO
CREATE LOGIN login_usuario   WITH PASSWORD = 'Usuario#2026!',   CHECK_POLICY = ON;
GO
CREATE LOGIN login_operativo WITH PASSWORD = 'Operativo#2026!', CHECK_POLICY = ON;
GO

CREATE USER usr_app       FOR LOGIN login_app;
GO
CREATE USER usr_admin     FOR LOGIN login_admin;
GO
CREATE USER usr_usuario   FOR LOGIN login_usuario;
GO
CREATE USER usr_operativo FOR LOGIN login_operativo;
GO

ALTER ROLE rol_admin     ADD MEMBER usr_admin;
GO
ALTER ROLE rol_usuario   ADD MEMBER usr_usuario;
GO
ALTER ROLE rol_operativo ADD MEMBER usr_operativo;
GO

-- =============================================
-- Permisos por rol
-- =============================================

-- Admin: control total
GRANT CREATE TABLE TO rol_admin;
GRANT CONTROL ON SCHEMA::personas    TO rol_admin;
GRANT CONTROL ON SCHEMA::catalogo    TO rol_admin;
GRANT CONTROL ON SCHEMA::operaciones TO rol_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::personas    TO rol_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::catalogo    TO rol_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::operaciones TO rol_admin;
GO

-- Usuario: solo lectura del catalogo
GRANT SELECT ON SCHEMA::catalogo    TO rol_usuario;
GRANT SELECT ON SCHEMA::operaciones TO rol_usuario;
DENY  INSERT, UPDATE, DELETE ON SCHEMA::catalogo    TO rol_usuario;
DENY  INSERT, UPDATE, DELETE ON SCHEMA::operaciones TO rol_usuario;
GO

-- Operativo: gestiona datos, sin DDL
GRANT SELECT, INSERT, UPDATE ON SCHEMA::personas            TO rol_operativo;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::catalogo    TO rol_operativo;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::operaciones TO rol_operativo;
DENY  CREATE TABLE TO rol_operativo;
DENY  CONTROL ON SCHEMA::personas    TO rol_operativo;
DENY  CONTROL ON SCHEMA::catalogo    TO rol_operativo;
DENY  CONTROL ON SCHEMA::operaciones TO rol_operativo;
GO

-- =============================================
-- Indices
-- =============================================

CREATE INDEX IX_BusquedaTitulo
ON catalogo.libros(titulo);
GO

CREATE INDEX IX_BuscarPrestamoUsuario
ON operaciones.prestamos(id_usuario);
GO

-- Indice para acelerar el login por correo
CREATE INDEX IX_LoginCorreo
ON personas.usuarios(correo);
GO

-- =============================================
-- Constraints CHECK adicionales
-- =============================================

ALTER TABLE catalogo.libros
ADD CONSTRAINT chk_ano_publicacion
CHECK (ano_publicacion >= 1500 AND ano_publicacion <= YEAR(GETDATE()));
GO

ALTER TABLE personas.usuarios
ADD CONSTRAINT chk_telefono
CHECK (LEN(telefono) >= 8);
GO

ALTER TABLE personas.usuarios
ADD CONSTRAINT chk_rol
CHECK (rol IN ('admin', 'operativo', 'usuario'));
GO

-- chk_password_hash eliminado: bcrypt produce hashes de 60 chars (no 64).
-- La longitud ya esta garantizada por la capa de aplicacion.

-- =============================================
-- Procedimiento de autenticacion
-- Busca el usuario por correo y devuelve sus datos
-- si el hash coincide. La app hace el hash antes de llamar.
-- Retorna 0 filas si las credenciales son incorrectas.
-- =============================================

-- La verificacion del hash bcrypt se realiza en Python (seguridad.py).
-- Este SP solo retorna los datos del usuario por correo; la app compara el hash.
CREATE PROCEDURE personas.autenticar_usuario
    @correo VARCHAR(150)
AS
BEGIN
    SET NOCOUNT ON;
    SELECT
        id_usuario,
        nombre_usuario,
        apellido_usuario,
        correo,
        rol,
        password_hash
    FROM personas.usuarios
    WHERE correo = @correo;
END;
GO

-- =============================================
-- Procedimientos operacionales
-- =============================================

CREATE PROCEDURE personas.registrar_usuario
    @nombre        VARCHAR(100),
    @apellido      VARCHAR(100),
    @correo        VARCHAR(150),
    @telefono      VARCHAR(20),
    @password_hash CHAR(64),
    @rol           VARCHAR(20) = 'usuario'
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO personas.usuarios
        (nombre_usuario, apellido_usuario, correo, telefono, password_hash, rol)
    VALUES
        (@nombre, @apellido, @correo, @telefono, @password_hash, @rol);
END;
GO

CREATE PROCEDURE operaciones.registrar_prestamo
    @id_usuario INT,
    @id_libro   INT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO operaciones.prestamos
        (id_usuario, id_libro, fecha_prestamo, estado)
    VALUES
        (@id_usuario, @id_libro, GETDATE(), 1);
END;
GO

CREATE PROCEDURE operaciones.devolver_libro
    @id_prestamo INT
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE operaciones.prestamos
    SET
        fecha_devolucion = GETDATE(),
        estado = 0
    WHERE id_prestamo = @id_prestamo;
END;
GO

CREATE PROCEDURE catalogo.buscar_libro
    @palabra VARCHAR(100)
AS
BEGIN
    SET NOCOUNT ON;
    SELECT
        l.id_libro,
        l.titulo,
        l.ano_publicacion,
        a.nombre_autor,
        a.apellido_autor,
        c.nombre_categoria
    FROM catalogo.libros l
    JOIN catalogo.autores a    ON l.id_autor     = a.id_autor
    JOIN catalogo.categorias c ON l.id_categoria = c.id_categoria
    WHERE l.titulo LIKE '%' + @palabra + '%';
END;
GO

-- =============================================
-- Permisos EXECUTE en stored procedures
-- =============================================

-- login_app: unico permiso es autenticar usuarios
GRANT EXECUTE ON personas.autenticar_usuario TO usr_app;
GO

-- Admin: puede ejecutar todos los procedimientos
GRANT EXECUTE ON personas.registrar_usuario     TO rol_admin;
GRANT EXECUTE ON operaciones.registrar_prestamo TO rol_admin;
GRANT EXECUTE ON operaciones.devolver_libro     TO rol_admin;
GRANT EXECUTE ON catalogo.buscar_libro          TO rol_admin;
GO

-- Operativo: gestiona prestamos y busca libros
GRANT EXECUTE ON operaciones.registrar_prestamo TO rol_operativo;
GRANT EXECUTE ON operaciones.devolver_libro     TO rol_operativo;
GRANT EXECUTE ON catalogo.buscar_libro          TO rol_operativo;
GO

-- Usuario: solo busqueda de libros
GRANT EXECUTE ON catalogo.buscar_libro TO rol_usuario;
GO

-- =============================================
-- Vistas
-- =============================================

CREATE VIEW catalogo.vista_libros_completa AS
SELECT
    l.id_libro,
    l.titulo,
    l.ano_publicacion,
    a.nombre_autor,
    a.apellido_autor,
    c.nombre_categoria
FROM catalogo.libros l
JOIN catalogo.autores a    ON l.id_autor     = a.id_autor
JOIN catalogo.categorias c ON l.id_categoria = c.id_categoria;
GO

CREATE VIEW operaciones.vista_prestamos_activos AS
SELECT
    p.id_prestamo,
    u.nombre_usuario,
    u.apellido_usuario,
    l.titulo,
    p.fecha_prestamo
FROM operaciones.prestamos p
JOIN personas.usuarios u ON p.id_usuario = u.id_usuario
JOIN catalogo.libros   l ON p.id_libro   = l.id_libro
WHERE p.estado = 1;
GO

-- =============================================
-- Datos iniciales
-- Los password_hash son bcrypt (rounds=12) generados desde Python.
-- Contrasenas:
--   Ana Rodriguez   -> "ana2026"
--   Carlos Mendez   -> "carlos2026"
--   Laura Sanchez   -> "laura2026"
--   Jose Fernandez  -> "jose2026"
--   Maria Lopez     -> "maria2026"
--   Daniel Vargas   -> "daniel2026"
--   Sofia Herrera   -> "sofia2026"
--   Luis Gomez      -> "luis2026"
--   Valeria Castro  -> "valeria2026"
--   Andres Morales  -> "admin2026"   (rol admin)
-- =============================================

INSERT INTO personas.usuarios
    (nombre_usuario, apellido_usuario, correo, telefono, password_hash, rol)
VALUES
    ('Ana',     'Rodriguez', 'ana.rodriguez@gmail.com',    '8845-1561',
     '$2b$12$I9YeMqafzStjKvFEXcm9bOaLLDDzNAov8WxcbwmiBCzVB9KzLX1rK', 'usuario'),
    ('Carlos',  'Mendez',    'carlos.mendez@gmail.com',    '7188-1067',
     '$2b$12$Rsq70pU9PNBbZhhckJv.8eYF/8tC5yfbkT1n/KhiC1pMigMkDaSma', 'operativo'),
    ('Laura',   'Sanchez',   'laura.sanchez@outlook.com',  '7458-1673',
     '$2b$12$K24T6/C9kFdGIswJri25ZOnYytwvDKn.5iYuf7TKitTOYBkfzudTC', 'usuario'),
    ('Jose',    'Fernandez', 'jose.fernandez@outlook.com', '8826-1894',
     '$2b$12$BU2F2oYbUhTQfWmFtfJUz.0EIHmncSQY.K9DPmW7Cg9kbUSQXDs06', 'usuario'),
    ('Maria',   'Lopez',     'maria.lopez@gmail.com',      '7478-1092',
     '$2b$12$uWZ6q7n5VLZBs./1dxpVn.TVQJl2DTuBQmfsg5M5ZNxg3riOAKoye', 'usuario'),
    ('Daniel',  'Vargas',    'daniel.vargas@outlook.com',  '7129-8364',
     '$2b$12$YCnh2cveMqNXgszpKU2HwurdaLdz5f88EgK0L74vOwfC9Uyk5KwBS', 'operativo'),
    ('Sofia',   'Herrera',   'sofia.herrera@gmail.com',    '8848-9823',
     '$2b$12$F/UxTkddYQeNxq5LobQ0Tujb50ul2Z74t.sFOaOQY0Ll3/YwTwLGy', 'usuario'),
    ('Luis',    'Gomez',     'luis.gomez@gmail.com',       '8812-1075',
     '$2b$12$ZWLRumio76KbdpZNaxWEH.czsQHjVOaDqfpOxfGzdvD0Wh25mpz5y', 'usuario'),
    ('Valeria', 'Castro',    'valeria.castro@gmail.com',   '7788-1009',
     '$2b$12$w8GGrIOdik5soUeCxe4hBu7AMss2m3QVhGgGDuImAnse4vVFwEz/W', 'usuario'),
    ('Andres',  'Morales',   'andres.morales@outlook.com', '8230-1010',
     '$2b$12$cW6bBYIbvJRLeNN3ynzae.xgk.bb4NJ54TeHnp427OnyY3PyRkkYy', 'admin');
GO

INSERT INTO catalogo.autores (nombre_autor, apellido_autor, nacionalidad)
VALUES
    ('Gabriel',   'Garcia Marquez', 'Colombiano'),
    ('Isabel',    'Allende',        'Chilena'),
    ('Julio',     'Cortazar',       'Argentino'),
    ('Jane',      'Austen',         'Britanica'),
    ('George',    'Orwell',         'Britanico'),
    ('Andrew S.', 'Tanenbaum',      'Estadounidense');
GO

INSERT INTO catalogo.categorias (nombre_categoria, descripcion)
VALUES
    ('Novela',              'Obras literarias de ficcion narrativa extensa'),
    ('Ciencia Ficcion',     'Libros basados en avances cientificos y mundos futuristas'),
    ('Historia',            'Libros sobre acontecimientos historicos y biografias'),
    ('Tecnologia',          'Libros relacionados con informatica y avances tecnologicos'),
    ('Literatura Infantil', 'Libros dirigidos a ninos y jovenes lectores');
GO

INSERT INTO catalogo.libros (titulo, ano_publicacion, id_autor, id_categoria)
VALUES
    ('Cien anos de soledad',        1967, 1, 1),
    ('El general en su laberinto',  1989, 1, 3),
    ('La luz es como el agua',      1978, 1, 5),
    ('La casa de los espiritus',    1982, 2, 1),
    ('Ines del alma mia',           2006, 2, 3),
    ('La cuidad de las bestias',    2002, 2, 5),
    ('Rayuela',                     1963, 3, 1),
    ('La autopista del sur',        1966, 3, 5),
    ('Casa tomada',                 1946, 3, 2),
    ('Orgullo y prejuicio',         1813, 4, 1),
    ('Persuasion',                  1817, 4, 3),
    ('Emma',                        1815, 4, 5),
    ('1984',                        1949, 5, 2),
    ('Animal Farm',                 1945, 5, 1),
    ('Homage to Catalonia',         1938, 5, 3),
    ('Computer networks',               1981, 6, 4),
    ('Modern Operating Systems',        1992, 6, 4),
    ('Structured Computer Organization',1976, 6, 4);
GO

INSERT INTO operaciones.prestamos (id_usuario, id_libro, fecha_prestamo, fecha_devolucion, estado)
VALUES
    (1, 1,  '2026-02-01', '2026-02-10', 0),
    (3, 4,  '2026-02-05', NULL,         1),
    (5, 13, '2026-02-07', NULL,         1),
    (2, 16, '2026-01-20', '2026-02-01', 0),
    (8, 7,  '2026-02-15', NULL,         1);
GO
