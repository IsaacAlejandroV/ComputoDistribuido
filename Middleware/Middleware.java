package middleware;
import java.net.*;
import java.io.*;

public class Middleware {

    private ServerSocket serverSocket;
    private Socket clientSocket;
    private PrintWriter out;
    private BufferedReader in;

    public void RecibirDatosMiddleware(int port) throws IOException {
        serverSocket = new ServerSocket(port);
        
        while(true){
            clientSocket = serverSocket.accept();
            out = new PrintWriter(clientSocket.getOutputStream(), true);
            in = new BufferedReader(new InputStreamReader(clientSocket.getInputStream()));

            String operacionRecibida = in.readLine();
            System.out.println("Recibido del cliente: " + operacionRecibida);

            if (operacionRecibida != null) {
                String resultado = enviarAServidorLogica(operacionRecibida);
                out.println(resultado); // regresa el resultado al cliente
                System.out.println("Resultado enviado al cliente: " + resultado);
            }

            clientSocket.close();
        }
       
    }
    
     private String enviarAServidorLogica(String datos) throws IOException {
        try (Socket servidorSocket = new Socket("127.0.0.1", 6668)) {
            PrintWriter outServidor = new PrintWriter(servidorSocket.getOutputStream(), true);
            BufferedReader inServidor = new BufferedReader(new InputStreamReader(servidorSocket.getInputStream()));

            outServidor.println(datos); // reenvía al servidor de lógica
            return inServidor.readLine(); // espera y regresa el resultado
        }
    }

    public void stop() throws IOException {
        in.close();
        out.close();
        clientSocket.close();
        serverSocket.close();
    }

    public static void main(String[] args) throws IOException {
        Middleware middleware = new Middleware();
        middleware.RecibirDatosMiddleware(6667); // se llama UNA sola vez
    }
}