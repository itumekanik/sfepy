#!/usr/bin/python
# 04.10.2005
# last revision: 03.09.2007
import sys
import os.path as op

if (len( sys.argv ) == 3):
    filename_in = sys.argv[1];
    filename_out = sys.argv[2];
else:
    print 'Usage: ', sys.argv[0], 'file.mesh file.vtk'
    sys.exit()

if (filename_in == '-'):
    file_in = sys.stdin
else:
    file_in = open( filename_in, "r" ); 

if (filename_out == '-'):
    file_out = sys.stdout
else:
    file_out = open( filename_out, "w" ); 

file_out.write( r"""# vtk DataFile Version 2.0
generated by %s
ASCII
DATASET UNSTRUCTURED_GRID
""" % op.basename( sys.argv[0] ) )

##
# 1. pass.
n_nod = 0
n_els = {'Edges' : 0, 'Quadrilaterals' : 0, 'Triangles' : 0,
        'Tetrahedra' : 0, 'Hexahedra' : 0 }
sizes = {'Edges' : 3, 'Quadrilaterals' : 5, 'Triangles' : 4,
         'Tetrahedra' : 5, 'Hexahedra' : 9 }
cell_types = {'Edges' : 3, 'Quadrilaterals' : 9, 'Triangles' : 5,
             'Tetrahedra' : 10, 'Hexahedra' : 12 }

keys = n_els.keys()
while 1:
    line = file_in.readline().split()
    if not len( line ):
        break
    elif (line[0] == 'Dimension'):
        if len( line ) == 2:
            dim = int( line[1] )
        else:
            dim = int( file_in.readline() )
    elif (line[0] == 'Vertices'):
        n_nod = int( file_in.readline() )
    elif (line[0] in keys):
        n_els[line[0]] += int( file_in.readline() )

n_el = sum( n_els.values() )
total_size = sum( [sizes[ii] * n_els[ii] for ii in n_els.keys()] )

#print n_nod, n_el, n_els, total_size

if (filename_in != '-'):
    file_in.close()
    file_in = open( filename_in, "r" ); 

end_node_line = (3 - dim) * '0.0 ' + '\n'

##
# 2. pass.
can_cells = 0
ct = []
mat_ids = []
while 1:
    line = file_in.readline().split()
    if not len( line ):
        break
    elif (line[0] == 'Vertices'):
        n_nod = int( file_in.readline() )
        file_out.write( 'POINTS %d float\n' % n_nod )
        for ii in range( n_nod ):
            line = file_in.readline().split()
            line[-1] = end_node_line
            file_out.write( ' '.join( line ) )

        file_out.write( 'CELLS %d %d\n' % (n_el, total_size) )
        can_cells = 1
    elif (line[0] in keys):
        if not can_cells:
            raise IOError

        nn = int( file_in.readline() )
        ct += [cell_types[line[0]]] * nn
        size = [str( sizes[line[0]] - 1 )]
        for ii in range( nn ):
            line = file_in.readline().split()
            mat_ids.append( line[-1] )
            aux = [str( int( ii ) - 1) for ii in line[:-1]] + ['\n']
            file_out.write( ' '.join( size + aux ) )

file_out.write( 'CELL_TYPES %d\n' % n_el )
file_out.write( ''.join( ['%d\n' % ii for ii in ct] ) )

file_out.write( 'CELL_DATA %d\n' % n_el )
file_out.write( '\nSCALARS mat_id int 1\n' )
file_out.write( 'LOOKUP_TABLE default\n' )
for row in mat_ids:
    file_out.write( '%s\n' % row )

if (filename_in != '-'):
    file_in.close()
if (filename_out != '-'):
    file_out.close()
