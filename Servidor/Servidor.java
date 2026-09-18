/*
 * Click nbfs://nbhost/SystemFileSystem/Templates/Licenses/license-default.txt to change this license
 * Click nbfs://nbhost/SystemFileSystem/Templates/Classes/Main.java to edit this template
 */
package servidor;
import java.net.*;
import java.io.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
/**
 *
 * @author Administrator
 */
public class Servidor {
    /**
     * @param args the command line arguments
     */
    private ServerSocket serverSocket;
    private ExecutorService pool;

    public Servidor(int numInstancias) {
        this.pool = Executors.newFixedThreadPool(numInstancias);
    }

    public void iniciar(int port) throws IOException {
        serverSocket = new ServerSocket(port);
        System.out.println("Servidor de lógica escuchando en puerto " + port);

        while (true) {
            Socket middlewareSocket = serverSocket.accept(); // acepta conexión
            pool.submit(() -> manejarConexion(middlewareSocket)); // la delega a un hilo del pool
        }
    }

    private void manejarConexion(Socket middlewareSocket) {
        try (
            middlewareSocket;
            PrintWriter out = new PrintWriter(middlewareSocket.getOutputStream(), true);
            BufferedReader in = new BufferedReader(new InputStreamReader(middlewareSocket.getInputStream()))
        ) {
            String datos = in.readLine();
            System.out.println("[" + Thread.currentThread().getName() + "] Recibido: " + datos);

            if (datos != null) {
                String resultado = calcular(datos);
                out.println(resultado);
                System.out.println("[" + Thread.currentThread().getName() + "] Resultado enviado: " + resultado);
            }
        } catch (IOException e) {
            System.out.println("Error manejando conexión: " + e.getMessage());
        }
    }

    private String calcular(String datos) {
        String[] partes = datos.split(",");
        long n1 = Long.parseLong(partes[0]);
        long n2 = Long.parseLong(partes[1]);
        String op = partes[2];

        try {
            long resultado = switch (op) {
                case "+" -> n1 + n2;
                case "-" -> n1 - n2;
                case "*" -> n1 * n2;
                case "/" -> n1 / n2;
                default -> 0;
            };
            return String.valueOf(resultado);
        } catch (ArithmeticException e) {
            return "Error: división entre cero";
        }
    }

    public static void main(String[] args) throws IOException {
        int numInstancias = 4; // cuántas peticiones simultáneas quieres atender
        Servidor servidor = new Servidor(numInstancias);
        servidor.iniciar(6668);
    }
    
}