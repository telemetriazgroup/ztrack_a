Tener en cuenta , hacer una interfaz para el control de maquina cerro_prieto que tiene "i":868428044554560 , que ingresa por post Termoking

En la interfaz se debe ver el ultimo dato ingresado  , de rs 
viene un ejemplo asi 
"rs": "RIPENER:0,20.0,26.8,27.3,27.1,29.2,0.0,0.0,0.0,0.0,90,0,0.0,0.0,95.0,2.0,0,0.0&REEFER_QUEST:1,5.0,5.1,6.5,2.2,36.3,0.0,0.0,0.0,0.0,82,10,1.2,19.2,254.0,1.0&INYECTOR:0000111101100010,1&",

se debe mostrar separado : 
RIPENER:0,20.0,26.8,27.3,27.1,29.2,0.0,0.0,0.0,0.0,90,0,0.0,0.0,95.0,2.0,0,0.0&

REEFER_QUEST:1,5.0,5.1,6.5,2.2,36.3,0.0,0.0,0.0,0.0,82,10,1.2,19.2,254.0,1.0&

INYECTOR:0000111101100010,1&"

y los datos de los datos del d02 

 "d02": "8.6,9.1,10.0,3.1,8.4,2.9,87.8,88.6,100.0,1,0,1,0,1,1",

 que especifique :
 Zona 1 CO2 : 8.6
 Zona 2 CO2 : 9.1
 Zona 3 CO2 : 10.0

 Zona 1 O2 : 3.1
 Zona 2 O2 : 8.4
 Zona 3 O2 : 2.9

 Zona 1 humedad : 87.8
 Zona 2 humedad : 88.6
 Zona 3 humedad : 100.0

y en la parte de abajo la opcion de enviar el comando al imei 868428044554560 ,

una lista de opciones con cada accion descrita a continuacion , y un modal que le diga lo que va hacer y el comando a enviar , y el ultimo dato recivido , si esta seguro , da en aceptar y recien se envia el comando , se muetsra estado de comando 1 pendiente , 0 activo , le muestra cual es el ultimo comando y si esta ejecutado(0) o pendiente (1)
Accion : Encender Nitrogeno zona 1: 
Comando : PANTALLA:NITRO1*

Encender Nitrogeno zona 2: 
PANTALLA:NITRO2*

Encender Nitrogeno zona 3: 
PANTALLA:NITRO3*

Apagar todos los nitrogenos: 
PANTALLA:NITRO0*


Encender CO2 zona 1: 
PANTALLA:CO2_1*

Encender CO2 zona 2: 
PANTALLA:CO2_2*

Encender CO2 zona 3: 
PANTALLA:CO2_3*

Apagar todas las zonas de CO2 : 
PANTALLA:CO2_0*


Encender Compresor 1: 
PANTALLA:COMP_1_ON*

Apagar Compresor 1: 
PANTALLA:COMP_1_OFF*

Encender Compresor 2:  
PANTALLA:COMP_2_ON*

Apagar Compresor 2:  
PANTALLA:COMP_2_OFF*

Activar bypass  pase oxígeno.
PANTALLA:INYECTOR:&O0*

Desactivar bypass de oxígeno.
PANTALLA:INYECTOR:&O1*




Encender Madurador
PANTALLA:MADURADOR_ENCENDER*

Apagar Madurador
PANTALLA:MADURADOR_APAGAR*



#LOgica de inyectores
En la trama "rs" , se tiene  -> RIPENER:0,20.0,24.9,26.5,24.9,30.1,0.0,0.0,0.0,0.0,90,0,0.0,20.7,95.0,2.0,0,0.5&REEFER_QUEST:1,5.0,5.3,6.7,2.3,39.0,28.0,0.0,0.0,0.0,81,0,0.0,0.0,254.0,-38.5&INYECTOR:0000111111100000,1& 

En el sector que analizamos 
INYECTOR:0000111111100000,1&

SEPARAMOS SOLO -> 0000111111100000

Entender :
1-> APAGADO
0 -> ENCENDIDO

-> 4 PRIMEROS NO SE CUENTAN 
0000111111100000
LLAMAREMOS -> ABCDEFGHIJKLMNOP
0000-> SIN USAR ABCD

1->E-> valvula de CO2 ZONA 1
1->F->valvula de CO2 ZONA 2
1->G->valvula de C02 ZONA 3

1->H->valvula de NITROGENO ZONA 3
1->I->valvula de NITROGENO ZONA 2
1->J->valvula de NITROGENO ZONA 1

1000->KLMN ->NO SE UTILIZA

0->O-> BYPASS DE OXÍGENO
0->P-> NO SE UTILIZA

